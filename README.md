# AI Meeting Assistant

Production-grade backend that ingests meeting recordings, transcribes them,
generates summaries/action items via LLM, and answers questions about past
meetings using RAG over a vector store.

## Status: Day 0 complete
- FastAPI skeleton with structured (JSON) logging
- Presigned-URL S3 upload flow (client uploads directly to S3)
- Postgres persistence for meeting lifecycle (SQLAlchemy async)
- Health/readiness endpoints for load balancer checks
- Dockerized, docker-compose stack (API + Postgres + Redis + Qdrant)

## Quickstart (local)

```bash
cp .env.example .env          # fill in AWS creds, S3 bucket, Anthropic key
docker compose up --build
```

API docs: http://localhost:8000/docs

## Try the upload flow

```bash
# 1. Request a presigned upload URL
curl -X POST http://localhost:8000/api/v1/meetings/upload-url \
  -H "X-User-Id: demo-user" \
  -H "Content-Type: application/json" \
  -d '{"filename": "standup.mp3", "content_type": "audio/mpeg", "title": "Daily Standup"}'

# 2. PUT the actual audio file to the returned upload_url
curl -X PUT "<upload_url>" --upload-file ./standup.mp3 -H "Content-Type: audio/mpeg"

# 3. Confirm upload (flips status to 'queued')
curl -X POST http://localhost:8000/api/v1/meetings/<meeting_id>/confirm \
  -H "X-User-Id: demo-user"

# 4. Poll status
curl http://localhost:8000/api/v1/meetings/<meeting_id> -H "X-User-Id: demo-user"
```

## Roadmap
See project plan — Day 1: Celery worker + job queue. Day 2: transcription
pipeline. Day 3: LLM summarization. Day 4: RAG Q&A. Day 5: auth. Day 6:
tests/hardening. Day 7: AWS deployment.
