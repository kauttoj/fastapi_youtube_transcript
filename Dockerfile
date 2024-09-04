# Use an official Python runtime as a parent image
FROM python:3.11-slim

LABEL maintainer="JanneK"

ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt ./

# Install Python dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app directory contents into the container at /app
COPY . /app

# Create a directory for the SQLite database
RUN mkdir -p /app/data

# Move the database file to the /app/data directory
COPY video_transcripts.db /app/data/

# Ensure that the /app/data directory has the correct write permissions
RUN chmod -R 755 /app/data

RUN chgrp -R 0 /app/data && chmod -R g=u /app/data 

# Expose the port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]