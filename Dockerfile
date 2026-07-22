# Use official Python image for ECS
FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

ARG GIT_SHA=unknown
ARG BUILD_ID=unknown
ARG RELEASE_VERSION=unknown
ENV GIT_SHA=$GIT_SHA \
    BUILD_ID=$BUILD_ID \
    RELEASE_VERSION=$RELEASE_VERSION

# Copy app code and requirements
COPY . /app
RUN pip install --no-cache-dir -r /app/requirements.txt

# Ensure prestart hook is executable (tiangolo base image runs /app/prestart.sh if present)
RUN chmod +x /app/prestart.sh

# Copy RDS global bundle certificate from local directory
COPY rds-global-bundle.pem /app/rds-global-bundle.pem

# Use the base image default command (gunicorn/uvicorn) to run the FastAPI app