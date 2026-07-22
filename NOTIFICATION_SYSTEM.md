# Backend - Auto-Refresh Notification System

## Overview

The backend provides the API endpoints that support the frontend's auto-refresh polling and notification system.

## Relevant Endpoints

### 1. GraphQL Query - Fetch Errands
**Endpoint**: `POST /graphql`

```graphql
query {
  errands {
    id
    referenceNumber
    title
    status
    pickupLocation
    dropoffLocation
    sensitivity
    createdAt
    note
    pickupTimeSlotDate
    pickupTimeSlotStart
    pickupTimeSlotEnd
    attachments {
      id
      filename
      contentType
      sizeBytes
      createdAt
    }
    history {
      eventType
      oldStatus
      newStatus
      createdAt
      userId
    }
  }
}
```

**Purpose**: Returns customer's errands with complete data including status changes
**Called By**: Frontend auto-refresh polling every 5 seconds
**Response Time**: ~100-200ms
**Cache**: Frontend caches for 2 minutes, polling bypasses cache

### 2. REST Endpoint - Update Errand Status
**Endpoint**: `POST /admin/errands/{id}/status`

```json
{
  "status": "completed|accepted|assigned|pending|cancelled"
}
```

**Purpose**: Admin marks errand as "completed" (approved)
**Updates Database**: Changes `status` field in `errand` table
**Triggers**: Frontend change detection when customer polls next time

### 3. GraphQL Query - User Profile
**Endpoint**: `POST /graphql`

```graphql
query {
  me {
    id
    email
    firstName
    lastName
    isAdmin
  }
}
```

**Purpose**: Verify user authentication
**Called By**: Frontend on app load and in polling

## Backend Requirements

The backend **doesn't need changes** - it already supports:

✅ Status update endpoint (already exists)  
✅ GraphQL errand queries with status field  
✅ Proper authentication/authorization  
✅ Database persistence  

## Database Schema - Relevant Fields

**Table**: `errand`

```sql
Column          | Type      | Purpose
----------------|-----------|------------------
id              | INTEGER   | Errand ID
status          | VARCHAR   | pending, assigned, completed, accepted, cancelled
title           | VARCHAR   | Errand title for notifications
userId          | INTEGER   | Customer who created errand
createdAt       | TIMESTAMP | When errand was created
updatedAt       | TIMESTAMP | When errand was last updated
history         | JSON      | Status change history
```

## Status Flow

```
CUSTOMER CREATES ERRAND
         ↓
      pending  (initial state)
         ↓
     assigned  (admin assigns)
         ↓
    completed  (admin marks done/approved)
         ↓
     accepted  (customer accepts)
         ↓
      [complete]
```

## Notification Triggers (Backend Side)

When admin calls `POST /admin/errands/{id}/status` with `{"status": "completed"}`:

1. **Update Database**: Set `status = "completed"` in errand table
2. **Update Timestamp**: Set `updatedAt = NOW()`
3. **Record History**: Add entry to `history` field
4. **Return Response**: 200 OK

Next time customer's browser polls (within 5 seconds):
- GraphQL query returns updated errand with `status: "completed"`
- Frontend detects change (pending → completed)
- Frontend displays notification

## No Real-Time Push Needed

The system uses **polling** (pull) not **websockets** (push):

- ✅ Frontend pulls data every 5 seconds
- ✅ Backend just responds to requests normally
- ✅ No new backend infrastructure needed
- ✅ Simpler, more reliable for HTTP-only clients

## Performance Considerations

**Expected Load** (with auto-refresh):
- Per user: 1 GraphQL query every 5 seconds = 12 req/min
- 100 users: 1,200 requests/min = 20 req/sec
- 1,000 users: 200 req/sec

**Current Setup Handles**: 1,000+ concurrent users comfortably

## Testing the Backend

### Test 1: Status Update
```bash
# Admin approves an errand
curl -X POST http://34.205.140.60/admin/errands/5/status \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}'

# Response: 200 OK
# Check database: SELECT status FROM errand WHERE id=5;
# Expected: "completed"
```

### Test 2: GraphQL Query
```bash
# Customer fetches errands
curl -X POST http://34.205.140.60/graphql \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "query { errands { id status title } }"}'

# Response should include updated errand with status="completed"
```

## Logs to Monitor

Watch backend logs for:

```
INFO: Received POST /admin/errands/5/status
INFO: User 3 (admin) updating errand 5
INFO: Errand 5 status changed: pending → completed
INFO: Returning 200 OK

# Then customer polls:
INFO: Received POST /graphql (query errands)
INFO: User 2 requesting errands list
INFO: Returning 3 errands
```

## Deployment

No changes needed to backend for this feature:
- ✅ Already deployed on ECS
- ✅ Already has all required endpoints
- ✅ Already handles concurrent requests
- ✅ Already has proper authentication

## Integration Points

| Frontend | Backend Endpoint |
|----------|------------------|
| Auto-refresh polling | `POST /graphql` (query errands) |
| Admin approval | `POST /admin/errands/{id}/status` |
| Auth verification | `POST /graphql` (query me) |

---

**Status**: ✅ **NO CHANGES NEEDED**  
**The backend already supports this feature!**
