from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from youtube_transcript_api import YouTubeTranscriptApi
import uvicorn
import requests
from dotenv import dotenv_values
import sqlite3
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from typing import List
import os
import logging

DB_PATH = r"/app/data/" # Adjust this path as needed
DB_NAME = 'video_transcripts.db'

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config = {}
try:
    # Create this file, it must contain following string:
    # YOUTUBE_KEY = "<your api key>"
    config = {**dotenv_values(".env")}
except:
    logger.warning('Unable to load .env file!')

app = FastAPI()

class VideoRequest(BaseModel):
    url: HttpUrl

def get_db_connection():
    return sqlite3.connect(os.path.join(DB_PATH, DB_NAME))

def init_db():
    logger.debug(f"Initializing database at {DB_PATH}")
    logger.debug(f"Current working directory: {os.getcwd()}")
    logger.debug(f"Directory contents: {os.listdir(DB_PATH)}")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  video_id TEXT UNIQUE,
                  url TEXT,
                  title TEXT,
                  description TEXT,
                  transcript TEXT,
                  processed_at TIMESTAMP)''')
    conn.commit()
    conn.close()
    logger.debug("Database initialized successfully")

def insert_video_data(video_id, url, title, description, transcript):
    logger.info(f"Inserting data for video {video_id}")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO videos 
                 (video_id, url, title, description, transcript, processed_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (video_id, url, title, description, transcript, datetime.now()))
    conn.commit()
    conn.close()
    logger.info(f"Data inserted successfully for video {video_id}")

def get_video_from_db(video_id):
    logger.debug(f"Fetching data for video {video_id}")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT title, description, transcript FROM videos WHERE video_id = ?', (video_id,))
    result = c.fetchone()
    conn.close()
    if result:
        logger.debug(f"Data found for video {video_id}")
        return {'title': result[0], 'description': result[1], 'transcript': result[2]}
    logger.debug(f"No data found for video {video_id}")
    return None

def get_video_description(video_id):
    """
    Fetches the video description using the YouTube Data API.
    """
    try:
        api_key = config["YOUTUBE_KEY"]
        assert len(api_key) > 10
    except:
        logger.error('Failed to obtain valid API key!')
        return {"title": "not available", "description": "not available"}

    url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={api_key}"

    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if 'items' in data and len(data['items']) > 0:
            snippet = data['items'][0]['snippet']
            return {
                'title': snippet['title'],
                'description': snippet['description']
            }

    return {
        'title': 'NaN',
        'description': 'NaN'
    }

def get_video_id(youtube_url):
    """
    Extracts the video ID from various forms of YouTube URLs.
    """
    parsed_url = urlparse(youtube_url)

    if parsed_url.hostname in ('youtu.be', 'www.youtu.be'):
        return parsed_url.path.lstrip('/')

    if parsed_url.hostname in ('youtube.com', 'www.youtube.com'):
        if parsed_url.path == '/watch':
            return parse_qs(parsed_url.query)['v'][0]
        if parsed_url.path.startswith(('/embed/', '/v/')):
            return parsed_url.path.split('/')[2]

    raise ValueError("Invalid YouTube URL")

def format_transcript_with_timestamps(transcript):
    """
    Formats the transcript with timestamps.
    """
    formatted_transcript = []
    for entry in transcript:
        start_time = entry['start']
        text = entry['text']

        # Convert start time from seconds to a readable format (HH:MM:SS)
        hours, remainder = divmod(start_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        timestamp = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

        # Append the formatted string to the list
        formatted_transcript.append(f"[{timestamp}] {text}")

    return "\n".join(formatted_transcript)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

class DatabaseStatus(BaseModel):
    total_videos: int
    video_ids: List[str]

@app.get("/get_database_status", response_model=DatabaseStatus)
async def get_database_status():
    """
    Endpoint to get the status of the database, including total number of videos and list of video IDs.
    """
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Get total number of videos
        c.execute('SELECT COUNT(*) FROM videos')
        total_videos = c.fetchone()[0]

        # Get list of video IDs
        c.execute('SELECT video_id FROM videos')
        video_ids = [row[0] for row in c.fetchall()]

        conn.close()

        return DatabaseStatus(total_videos=total_videos, video_ids=video_ids)

    except Exception as e:
        logger.error(f"Failed to get database status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get database status: {str(e)}")

@app.post("/get_transcript/")
async def get_transcript(request: VideoRequest):
    """
    Endpoint to get the transcript of a YouTube video.
    """
    try:
        # Extract the video ID from the URL
        video_id = get_video_id(str(request.url))
        logger.info(f'Processing video ID: {video_id}')

        # Check if the video has already been processed
        existing_data = get_video_from_db(video_id)
        if existing_data:
            logger.info(f"Video {video_id} found in database. Returning stored data.")
            return {"transcript": existing_data['transcript']}

        # If not in database, process the video
        logger.info(f'Processing new video: {video_id}')

        # Fetch the transcript using the video ID
        transcript = YouTubeTranscriptApi.get_transcript(video_id,languages=['en','fi'])
        logger.info(f'Transcript has length {len(transcript)}')

        # Fetch the video description
        metainfo = get_video_description(video_id)

        # Format the transcript with timestamps
        formatted_transcript = format_transcript_with_timestamps(transcript)

        if len(formatted_transcript) <= 500:
            raise ValueError("Transcript too short!")

        formatted_transcript += '\nEND_OF_TRANSCRIPT'

        output = 'Title: ' + metainfo['title'].strip() + '\n\n' + formatted_transcript

        logger.info(f'Success! Final transcript length is {len(output)} with {len(output.splitlines())} lines')

        # Store the data in the database
        insert_video_data(video_id, str(request.url), metainfo['title'], metainfo['description'], output)
        logger.info(f'Added new video into database')

        return {"transcript": output}

    except Exception as e:
        logger.error(f"Failed to process video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to obtain transcript: {str(e)}")

init_db()

# # TESTING
# if 0:
#     test_url = "https://www.youtube.com/watch?v=aQ4yQXeB1Ss"  # Example URL for testing
#     video_id = get_video_id(test_url)
#
#     existing_data = get_video_from_db(video_id)
#     if existing_data:
#         print(f"Video {video_id} found in database. Returning stored data.")
#
#     transcript = YouTubeTranscriptApi.get_transcript(video_id)
#     metainfo = get_video_description(video_id)
#     formatted_transcript = format_transcript_with_timestamps(transcript)
#     assert len(formatted_transcript) > 500, "transcript too short!"
#     formatted_transcript += '\nEND_OF_TRANSCRIPT'
#     output = 'Title: ' + metainfo['title'].strip() + '\n\n' + formatted_transcript
#     insert_video_data(video_id,test_url, metainfo['title'], metainfo['description'], output)

#if __name__ == "__main__":
#    uvicorn.run(app, host="0.0.0.0", port=8000)