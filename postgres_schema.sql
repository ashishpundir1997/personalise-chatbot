-- ============================================
-- Postgres Table Creation SQL
-- ============================================
-- Copy and paste this into your Postgres SQL console
-- ============================================

-- Drop existing tables (in reverse order for foreign keys)
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Creating table: conversations

CREATE TABLE conversations (
	id UUID NOT NULL, 
	user_id VARCHAR NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_activity TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	message_count INTEGER NOT NULL, 
	name VARCHAR, 
	PRIMARY KEY (id)
)

;

-- Creating table: users

CREATE TABLE users (
	user_id VARCHAR NOT NULL, 
	email VARCHAR NOT NULL, 
	password_hash VARCHAR, 
	auth_provider VARCHAR, 
	auth_provider_detail JSONB, 
	name VARCHAR, 
	phone VARCHAR, 
	image_url VARCHAR, 
	is_email_verified BOOLEAN, 
	is_profile_created BOOLEAN, 
	profile_colour VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (user_id), 
	UNIQUE (email)
)

;

-- Creating table: messages

CREATE TABLE messages (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	sender_role VARCHAR NOT NULL, 
	content TEXT, 
	message_metadata JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
)

;

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_id ON conversations (id);
CREATE INDEX IF NOT EXISTS ix_messages_id ON messages (id);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id);

-- ============================================
-- Verify tables were created
-- ============================================
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
