# escape=`
# Use official Windows Server Core image with Python pre-installed
FROM python:3.11-windowsservercore-ltsc2022

# Configure working directory using forward slash for clean path parsing
WORKDIR C:/app

# Prevent Python from writing .pyc files & buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Copy dependency list
COPY requirements.txt .

# Install dependencies and Waitress WSGI server
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir waitress

# Copy application source code
COPY . .

# Expose internal port for IIS reverse proxy
EXPOSE 5000

# Run Flask using Waitress binding on port 5000
CMD ["waitress-serve", "--listen=0.0.0.0:5000", "app:app"]
