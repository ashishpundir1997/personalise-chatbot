# Redis vs Postgres Usage Logic

## ✅ Status: Working Fine
Based on the logs, the system is working correctly - messages are being stored successfully.

## Storage Strategy: Dual-Write Pattern

### **Writing Messages (`add_message` method)**
- **Redis**: Stores last **100 messages** per conversation (fast cache)
  - Line 25: `MAX_CACHED_MESSAGES = 100`
  - Lines 168-174: When adding a message:
    1. Get existing cached messages from Redis
    2. Append new message
    3. If > 100 messages, keep only last 100: `msgs[-100:]`
    4. Save back to Redis with 7-day TTL
  
- **Postgres**: Stores **ALL messages** permanently (persistent storage)
  - Lines 176-210: Every message is inserted into Postgres
  - Never truncated - complete history

**Result**: Every message is written to BOTH Redis (last 100) AND Postgres (all)

---

### **Reading Messages (`get_recent_messages` method)**
**Strategy**: Redis-first with Postgres fallback

1. **Try Redis first** (Lines 227-232):
   - Check if messages exist in Redis cache
   - If found: Return from Redis (fast path) ✅
   - Log: "Cache HIT"

2. **Fallback to Postgres** (Lines 234-261):
   - If Redis cache miss: Query Postgres
   - Get last N messages from Postgres
   - **Cache the result in Redis** for next time
   - Log: "Cache MISS"

**Result**: Fast reads from Redis when available, reliable fallback to Postgres

---

### **Reading Conversation Metadata (`get_conversation` method)**
**Strategy**: Redis-first with Postgres fallback

1. **Try Redis first** (Lines 123-133):
   - Check if conversation metadata exists in Redis
   - If found: Return from Redis ✅
   - Log: "Cache HIT"

2. **Fallback to Postgres** (Lines 135-155):
   - If Redis cache miss: Query Postgres
   - Get conversation from Postgres
   - **Cache the result in Redis** for next time
   - Log: "Cache MISS"

---

## Redis Configuration

### Message Caching
- **Max Messages in Redis**: **100 messages** per conversation
- **TTL**: 7 days (604,800 seconds)
- **Key Pattern**: 
  - `conversation:{conversation_id}` - conversation metadata
  - `conversation:{conversation_id}:messages` - message list

### When Messages are Trimmed
- **Line 172-173**: When adding a new message, if Redis has > 100 messages:
  ```python
  if len(msgs) > self.MAX_CACHED_MESSAGES:
      msgs = msgs[-self.MAX_CACHED_MESSAGES:]  # Keep only last 100
  ```

---

## Summary Table

| Operation | Redis Usage | Postgres Usage | Notes |
|-----------|------------|----------------|-------|
| **Write Message** | ✅ Last 100 messages | ✅ ALL messages | Dual-write |
| **Read Messages** | ✅ First (if cached) | ⚠️ Fallback (if cache miss) | Redis-first |
| **Read Conversation** | ✅ First (if cached) | ⚠️ Fallback (if cache miss) | Redis-first |
| **List Conversations** | ❌ Not used | ✅ Always | Postgres only |
| **Delete Conversation** | ✅ Delete cache | ✅ Delete from DB | Both |

---

## Current Behavior

✅ **Yes, we are keeping 100 messages in Redis caching**
- Line 25: `MAX_CACHED_MESSAGES = 100`
- Line 172-173: Automatic trimming when > 100 messages
- Handler requests up to 100 messages (line 154 in handler.py)

✅ **Redis is used for:**
- Fast reads of recent messages (last 100)
- Fast reads of conversation metadata
- Active conversation caching

✅ **Postgres is used for:**
- Permanent storage of ALL messages (no limit)
- Fallback when Redis cache is empty/expired
- Listing all conversations
- Complete message history

---

## Performance Benefits

1. **Fast Reads**: Recent messages served from Redis (in-memory)
2. **Reliability**: All data persisted in Postgres
3. **Scalability**: Redis handles hot data, Postgres handles cold data
4. **Cache Warming**: Postgres queries automatically populate Redis cache

