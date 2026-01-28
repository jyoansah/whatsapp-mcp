import sqlite3
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import os.path
import requests
import json
import audio

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
WHATSMEOW_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'whatsapp.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"

# Cache for contact names to avoid repeated database lookups
_contact_name_cache = {}

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: Optional[str] = None
    media_type: Optional[str] = None
    reply_to_id: Optional[str] = None
    reply_to_sender: Optional[str] = None
    reply_to_content: Optional[str] = None

@dataclass
class Chat:
    jid: str
    name: Optional[str]
    last_message_time: Optional[datetime]
    last_message: Optional[str] = None
    last_sender: Optional[str] = None
    last_is_from_me: Optional[bool] = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")

@dataclass
class Contact:
    phone_number: str
    name: Optional[str]
    jid: str

@dataclass
class MessageContext:
    message: Message
    before: List[Message]
    after: List[Message]

def get_contact_name_from_whatsmeow(jid: str) -> Optional[str]:
    """Get contact name from whatsmeow contacts table.

    Args:
        jid: The JID to look up (e.g., "233551749015@s.whatsapp.net" or "233551749015")

    Returns:
        The contact's display name (full_name, push_name, or business_name), or None if not found
    """
    global _contact_name_cache

    # Normalize JID - ensure it has the @s.whatsapp.net suffix for individual contacts
    normalized_jid = jid
    if '@' not in jid:
        normalized_jid = f"{jid}@s.whatsapp.net"

    # Check cache first
    if normalized_jid in _contact_name_cache:
        return _contact_name_cache[normalized_jid]

    try:
        conn = sqlite3.connect(WHATSMEOW_DB_PATH)
        cursor = conn.cursor()

        # Query whatsmeow_contacts table for the contact name
        # Priority: full_name > push_name > business_name
        cursor.execute("""
            SELECT full_name, push_name, business_name
            FROM whatsmeow_contacts
            WHERE their_jid = ?
            LIMIT 1
        """, (normalized_jid,))

        result = cursor.fetchone()

        if result:
            full_name, push_name, business_name = result
            # Return the first non-empty name
            name = full_name or push_name or business_name
            if name:
                _contact_name_cache[normalized_jid] = name
                return name

        # Also try without the suffix (in case JID format varies)
        if '@' in jid:
            phone_part = jid.split('@')[0]
            cursor.execute("""
                SELECT full_name, push_name, business_name
                FROM whatsmeow_contacts
                WHERE their_jid LIKE ?
                LIMIT 1
            """, (f"{phone_part}@%",))

            result = cursor.fetchone()
            if result:
                full_name, push_name, business_name = result
                name = full_name or push_name or business_name
                if name:
                    _contact_name_cache[normalized_jid] = name
                    return name

        # Cache the miss as None
        _contact_name_cache[normalized_jid] = None
        return None

    except sqlite3.Error as e:
        print(f"Database error while getting contact name from whatsmeow: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def get_sender_name(sender_jid: str) -> str:
    """Get display name for a sender JID.

    Looks up contact name from whatsmeow contacts first, then falls back to chats table.
    """
    # First try to get contact name from whatsmeow contacts
    contact_name = get_contact_name_from_whatsmeow(sender_jid)
    if contact_name:
        return contact_name

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # First try matching by exact JID
        cursor.execute("""
            SELECT name
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """, (sender_jid,))

        result = cursor.fetchone()

        # If no result, try looking for the number within JIDs
        if not result:
            # Extract the phone number part if it's a JID
            if '@' in sender_jid:
                phone_part = sender_jid.split('@')[0]
            else:
                phone_part = sender_jid

            cursor.execute("""
                SELECT name
                FROM chats
                WHERE jid LIKE ?
                LIMIT 1
            """, (f"%{phone_part}%",))

            result = cursor.fetchone()

        if result and result[0]:
            return result[0]
        else:
            # Return just the phone number part if we have a JID
            if '@' in sender_jid:
                return sender_jid.split('@')[0]
            return sender_jid

    except sqlite3.Error as e:
        print(f"Database error while getting sender name: {e}")
        return sender_jid
    finally:
        if 'conn' in locals():
            conn.close()

def format_message(message: Message, show_chat_info: bool = True) -> None:
    """Print a single message with consistent formatting."""
    output = ""

    if show_chat_info and message.chat_name:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] Chat: {message.chat_name} "
    else:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] "

    content_prefix = ""
    if hasattr(message, 'media_type') and message.media_type:
        content_prefix = f"[{message.media_type} - Message ID: {message.id} - Chat JID: {message.chat_jid}] "

    # Add reply context if this message is a reply
    reply_info = ""
    if message.reply_to_id:
        reply_sender = get_sender_name(message.reply_to_sender) if message.reply_to_sender else "Unknown"
        reply_content = message.reply_to_content or "[message]"
        if len(reply_content) > 50:
            reply_content = reply_content[:50] + "..."
        reply_info = f"[Reply to {reply_sender}: \"{reply_content}\"] "

    try:
        sender_name = get_sender_name(message.sender) if not message.is_from_me else "Me"
        output += f"From: {sender_name}: {reply_info}{content_prefix}{message.content}\n"
    except Exception as e:
        print(f"Error formatting message: {e}")
    return output

def format_messages_list(messages: List[Message], show_chat_info: bool = True) -> None:
    output = ""
    if not messages:
        output += "No messages to display."
        return output
    
    for message in messages:
        output += format_message(message, show_chat_info)
    return output

def list_messages(
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1
) -> List[Message]:
    """Get messages matching the specified criteria with optional context."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Build base query
        query_parts = ["SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.reply_to_id, messages.reply_to_sender, messages.reply_to_content FROM messages"]
        query_parts.append("JOIN chats ON messages.chat_jid = chats.jid")
        where_clauses = []
        params = []
        
        # Add filters
        if after:
            try:
                after = datetime.fromisoformat(after)
            except ValueError:
                raise ValueError(f"Invalid date format for 'after': {after}. Please use ISO-8601 format.")
            
            where_clauses.append("messages.timestamp > ?")
            params.append(after)

        if before:
            try:
                before = datetime.fromisoformat(before)
            except ValueError:
                raise ValueError(f"Invalid date format for 'before': {before}. Please use ISO-8601 format.")
            
            where_clauses.append("messages.timestamp < ?")
            params.append(before)

        if sender_phone_number:
            where_clauses.append("messages.sender = ?")
            params.append(sender_phone_number)
            
        if chat_jid:
            where_clauses.append("messages.chat_jid = ?")
            params.append(chat_jid)
            
        if query:
            where_clauses.append("LOWER(messages.content) LIKE LOWER(?)")
            params.append(f"%{query}%")
            
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))
            
        # Add pagination
        offset = page * limit
        query_parts.append("ORDER BY messages.timestamp DESC")
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        
        cursor.execute(" ".join(query_parts), tuple(params))
        messages = cursor.fetchall()
        
        result = []
        for msg in messages:
            message = Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7],
                reply_to_id=msg[8],
                reply_to_sender=msg[9],
                reply_to_content=msg[10]
            )
            result.append(message)
            
        if include_context and result:
            # Add context for each message
            messages_with_context = []
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after)
                messages_with_context.extend(context.before)
                messages_with_context.append(context.message)
                messages_with_context.extend(context.after)
            
            return format_messages_list(messages_with_context, show_chat_info=True)
            
        # Format and display messages without context
        return format_messages_list(result, show_chat_info=True)    
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> MessageContext:
    """Get context around a specific message."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Get the target message first
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.chat_jid, messages.media_type, messages.reply_to_id, messages.reply_to_sender, messages.reply_to_content
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.id = ?
        """, (message_id,))
        msg_data = cursor.fetchone()

        if not msg_data:
            raise ValueError(f"Message with ID {message_id} not found")

        target_message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[8],
            reply_to_id=msg_data[9],
            reply_to_sender=msg_data[10],
            reply_to_content=msg_data[11]
        )
        
        # Get messages before
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.reply_to_id, messages.reply_to_sender, messages.reply_to_content
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp < ?
            ORDER BY messages.timestamp DESC
            LIMIT ?
        """, (msg_data[7], msg_data[0], before))

        before_messages = []
        for msg in cursor.fetchall():
            before_messages.append(Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7],
                reply_to_id=msg[8],
                reply_to_sender=msg[9],
                reply_to_content=msg[10]
            ))

        # Get messages after
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.reply_to_id, messages.reply_to_sender, messages.reply_to_content
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp > ?
            ORDER BY messages.timestamp ASC
            LIMIT ?
        """, (msg_data[7], msg_data[0], after))

        after_messages = []
        for msg in cursor.fetchall():
            after_messages.append(Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7],
                reply_to_id=msg[8],
                reply_to_sender=msg[9],
                reply_to_content=msg[10]
            ))
        
        return MessageContext(
            message=target_message,
            before=before_messages,
            after=after_messages
        )
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Chat]:
    """Get chats matching the specified criteria."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Build base query
        query_parts = ["""
            SELECT 
                chats.jid,
                chats.name,
                chats.last_message_time,
                messages.content as last_message,
                messages.sender as last_sender,
                messages.is_from_me as last_is_from_me
            FROM chats
        """]
        
        if include_last_message:
            query_parts.append("""
                LEFT JOIN messages ON chats.jid = messages.chat_jid 
                AND chats.last_message_time = messages.timestamp
            """)
            
        where_clauses = []
        params = []
        
        if query:
            where_clauses.append("(LOWER(chats.name) LIKE LOWER(?) OR chats.jid LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
            
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))
            
        # Add sorting
        order_by = "chats.last_message_time DESC" if sort_by == "last_active" else "chats.name"
        query_parts.append(f"ORDER BY {order_by}")
        
        # Add pagination
        offset = (page ) * limit
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        
        cursor.execute(" ".join(query_parts), tuple(params))
        chats = cursor.fetchall()
        
        result = []
        for chat_data in chats:
            jid = chat_data[0]
            name = chat_data[1]

            # For individual chats (not groups), try to get contact name from whatsmeow
            if not jid.endswith("@g.us"):
                contact_name = get_contact_name_from_whatsmeow(jid)
                if contact_name:
                    name = contact_name
                elif not name:
                    # If no name found anywhere, use phone number
                    name = jid.split('@')[0] if '@' in jid else jid

            chat = Chat(
                jid=jid,
                name=name,
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5]
            )
            result.append(chat)

        return result

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def search_contacts(query: str) -> List[Contact]:
    """Search contacts by name or phone number.

    Searches both the chats table and whatsmeow contacts for matching contacts.
    """
    result = []
    seen_jids = set()

    # First, search whatsmeow contacts (more accurate names)
    try:
        conn = sqlite3.connect(WHATSMEOW_DB_PATH)
        cursor = conn.cursor()

        search_pattern = f'%{query}%'

        cursor.execute("""
            SELECT DISTINCT
                their_jid,
                full_name,
                push_name,
                business_name
            FROM whatsmeow_contacts
            WHERE
                (LOWER(full_name) LIKE LOWER(?) OR
                 LOWER(push_name) LIKE LOWER(?) OR
                 LOWER(business_name) LIKE LOWER(?) OR
                 their_jid LIKE ?)
                AND their_jid NOT LIKE '%@g.us'
            ORDER BY full_name, push_name, their_jid
            LIMIT 50
        """, (search_pattern, search_pattern, search_pattern, search_pattern))

        contacts = cursor.fetchall()

        for contact_data in contacts:
            jid = contact_data[0]
            full_name, push_name, business_name = contact_data[1], contact_data[2], contact_data[3]
            name = full_name or push_name or business_name

            if jid not in seen_jids:
                contact = Contact(
                    phone_number=jid.split('@')[0] if '@' in jid else jid,
                    name=name,
                    jid=jid
                )
                result.append(contact)
                seen_jids.add(jid)

    except sqlite3.Error as e:
        print(f"Database error while searching whatsmeow contacts: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

    # Then search chats table for any additional contacts
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        search_pattern = f'%{query}%'

        cursor.execute("""
            SELECT DISTINCT
                jid,
                name
            FROM chats
            WHERE
                (LOWER(name) LIKE LOWER(?) OR LOWER(jid) LIKE LOWER(?))
                AND jid NOT LIKE '%@g.us'
            ORDER BY name, jid
            LIMIT 50
        """, (search_pattern, search_pattern))

        contacts = cursor.fetchall()

        for contact_data in contacts:
            jid = contact_data[0]
            if jid not in seen_jids:
                # Try to get contact name from whatsmeow first
                name = get_contact_name_from_whatsmeow(jid) or contact_data[1]
                if not name:
                    name = jid.split('@')[0] if '@' in jid else jid

                contact = Contact(
                    phone_number=jid.split('@')[0] if '@' in jid else jid,
                    name=name,
                    jid=jid
                )
                result.append(contact)
                seen_jids.add(jid)

    except sqlite3.Error as e:
        print(f"Database error while searching chats: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

    return result


def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Chat]:
    """Get all chats involving the contact.
    
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
            JOIN messages m ON c.jid = m.chat_jid
            WHERE m.sender = ? OR c.jid = ?
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """, (jid, jid, limit, page * limit))
        
        chats = cursor.fetchall()

        result = []
        for chat_data in chats:
            chat_jid = chat_data[0]
            name = chat_data[1]

            # For individual chats (not groups), try to get contact name from whatsmeow
            if not chat_jid.endswith("@g.us"):
                contact_name = get_contact_name_from_whatsmeow(chat_jid)
                if contact_name:
                    name = contact_name
                elif not name:
                    name = chat_jid.split('@')[0] if '@' in chat_jid else chat_jid

            chat = Chat(
                jid=chat_jid,
                name=name,
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5]
            )
            result.append(chat)

        return result

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_last_interaction(jid: str) -> str:
    """Get most recent message involving the contact."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                m.timestamp,
                m.sender,
                c.name,
                m.content,
                m.is_from_me,
                c.jid,
                m.id,
                m.media_type,
                m.reply_to_id,
                m.reply_to_sender,
                m.reply_to_content
            FROM messages m
            JOIN chats c ON m.chat_jid = c.jid
            WHERE m.sender = ? OR c.jid = ?
            ORDER BY m.timestamp DESC
            LIMIT 1
        """, (jid, jid))

        msg_data = cursor.fetchone()

        if not msg_data:
            return None

        message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[7],
            reply_to_id=msg_data[8],
            reply_to_sender=msg_data[9],
            reply_to_content=msg_data[10]
        )

        return format_message(message)
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def get_chat(chat_jid: str, include_last_message: bool = True) -> Optional[Chat]:
    """Get chat metadata by JID."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        query = """
            SELECT
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
        """

        if include_last_message:
            query += """
                LEFT JOIN messages m ON c.jid = m.chat_jid
                AND c.last_message_time = m.timestamp
            """

        query += " WHERE c.jid = ?"

        cursor.execute(query, (chat_jid,))
        chat_data = cursor.fetchone()

        if not chat_data:
            return None

        jid = chat_data[0]
        name = chat_data[1]

        # For individual chats (not groups), try to get contact name from whatsmeow
        if not jid.endswith("@g.us"):
            contact_name = get_contact_name_from_whatsmeow(jid)
            if contact_name:
                name = contact_name
            elif not name:
                name = jid.split('@')[0] if '@' in jid else jid

        return Chat(
            jid=jid,
            name=name,
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5]
        )

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def get_direct_chat_by_contact(sender_phone_number: str) -> Optional[Chat]:
    """Get chat metadata by sender phone number."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
            LEFT JOIN messages m ON c.jid = m.chat_jid
                AND c.last_message_time = m.timestamp
            WHERE c.jid LIKE ? AND c.jid NOT LIKE '%@g.us'
            LIMIT 1
        """, (f"%{sender_phone_number}%",))

        chat_data = cursor.fetchone()

        if not chat_data:
            return None

        jid = chat_data[0]
        name = chat_data[1]

        # Try to get contact name from whatsmeow
        contact_name = get_contact_name_from_whatsmeow(jid)
        if contact_name:
            name = contact_name
        elif not name:
            name = jid.split('@')[0] if '@' in jid else jid

        return Chat(
            jid=jid,
            name=name,
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5]
        )

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

def send_message(recipient: str, message: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message,
        }

        response = requests.post(url, json=payload)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_reply(recipient: str, message: str, reply_to_id: str, reply_to_jid: str) -> Tuple[bool, str]:
    """Send a reply to a specific WhatsApp message.

    Args:
        recipient: Phone number or JID of the chat to send to
        message: Message text to send
        reply_to_id: ID of the message being replied to
        reply_to_jid: JID of the sender of the message being replied to

    Returns:
        Tuple of (success, status_message)
    """
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        if not reply_to_id:
            return False, "reply_to_id must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message,
            "reply_to_id": reply_to_id,
            "reply_to_jid": reply_to_jid,
        }

        response = requests.post(url, json=payload)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_file(recipient: str, media_path: str = "", media_data: str = "", filename: str = "") -> Tuple[bool, str]:
    """Send a file via WhatsApp.

    Priority order:
    1. media_data (base64) - highest priority, best for local files
    2. media_path with URL - for remote files
    3. media_path with path - for container-accessible paths only

    Args:
        recipient: Phone number or JID
        media_path: URL or container-accessible file path
        media_data: Base64-encoded file data (takes priority)
        filename: Original filename (required with media_data)

    Returns:
        Tuple of (success, message)
    """
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path and not media_data:
            return False, "Either media_path (URL or path) or media_data (base64) must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient}

        # Priority: media_data > media_url > media_path
        if media_data:
            # Base64 data provided - highest priority
            payload["media_data"] = media_data
            if filename:
                payload["filename"] = filename
        elif media_path.startswith("http://") or media_path.startswith("https://"):
            # It's a URL - send via media_url parameter
            payload["media_url"] = media_path
        else:
            # It's a local path - check if accessible before sending
            if not os.path.isfile(media_path):
                # File not found - provide helpful guidance
                return False, (
                    f"Media file not found: {media_path}. "
                    "This MCP runs in a container and cannot access host filesystem paths. "
                    "Please use one of these alternatives:\n"
                    "1. media_data: Pass base64-encoded file content (recommended)\n"
                    "2. media_path with URL: Provide an http:// or https:// URL\n"
                    "3. Container path: Use paths under /app/store/ (mounted volume)"
                )
            payload["media_path"] = media_path

        response = requests.post(url, json=payload)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_audio_message(recipient: str, media_path: str) -> Tuple[bool, str]:
    """Send an audio file as a WhatsApp voice message.

    The media_path can be:
    - A local file path (will be read by the Go bridge)
    - A remote URL starting with http:// or https:// (will be downloaded by the Go bridge)

    Note: For proper voice message display, the file should be in OGG Opus format.
    For local files, this function can convert them using ffmpeg.
    For URLs, ensure the file is already in OGG Opus format.

    Args:
        recipient: Phone number or JID
        media_path: Local file path or remote URL

    Returns:
        Tuple of (success, message)
    """
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path:
            return False, "Media path or URL must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"

        # Check if media_path is a URL or a local path
        if media_path.startswith("http://") or media_path.startswith("https://"):
            # It's a URL - send via media_url parameter
            # For URLs, we assume the file is already in the correct format
            payload = {
                "recipient": recipient,
                "media_url": media_path
            }
        else:
            # It's a local path
            # Check if the file exists locally and can be converted
            if os.path.isfile(media_path):
                if not media_path.endswith(".ogg"):
                    try:
                        media_path = audio.convert_to_opus_ogg_temp(media_path)
                    except Exception as e:
                        return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"

            # Send via media_path parameter - Go bridge will read the file
            payload = {
                "recipient": recipient,
                "media_path": media_path
            }

        response = requests.post(url, json=payload)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

@dataclass
class DownloadedMedia:
    success: bool
    message: str
    filename: Optional[str] = None
    path: Optional[str] = None
    media_url: Optional[str] = None
    public_url: Optional[str] = None
    media_type: Optional[str] = None
    access_note: Optional[str] = None


def download_media(message_id: str, chat_jid: str) -> dict:
    """Download media from a message and return information about how to access it.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        A dictionary containing:
        - success: Whether the download succeeded
        - message: Status message
        - filename: Name of the downloaded file
        - path: Local file path on the server
        - public_url: Full URL for external access (if WHATSAPP_PUBLIC_URL is configured)
        - media_type: Type of media (image, video, audio, document)
        - access_note: Instructions for accessing the media
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {
            "message_id": message_id,
            "chat_jid": chat_jid
        }

        response = requests.post(url, json=payload)

        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                filename = result.get("filename")
                media_url = result.get("media_url")  # Relative URL path
                public_url = result.get("public_url")  # Full public URL from bridge
                media_type = result.get("media_type")
                access_note = result.get("access_note")

                print(f"Media downloaded successfully: {path}")
                print(f"Public URL: {public_url}")
                print(f"Access note: {access_note}")

                return {
                    "success": True,
                    "message": f"Successfully downloaded {media_type} media",
                    "filename": filename,
                    "path": path,
                    "public_url": public_url,
                    "media_type": media_type,
                    "access_note": access_note
                }
            else:
                error_msg = result.get('message', 'Unknown error')
                print(f"Download failed: {error_msg}")
                return {
                    "success": False,
                    "message": f"Download failed: {error_msg}"
                }
        else:
            error_msg = f"HTTP {response.status_code} - {response.text}"
            print(f"Error: {error_msg}")
            return {
                "success": False,
                "message": f"Error: {error_msg}"
            }

    except requests.RequestException as e:
        error_msg = f"Request error: {str(e)}"
        print(error_msg)
        return {
            "success": False,
            "message": error_msg
        }
    except json.JSONDecodeError:
        error_msg = f"Error parsing response: {response.text}"
        print(error_msg)
        return {
            "success": False,
            "message": error_msg
        }
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        return {
            "success": False,
            "message": error_msg
        }


# Scheduling functions

@dataclass
class ScheduledMessage:
    id: int
    recipient: str
    message: str
    media_path: Optional[str]
    scheduled_time: datetime
    status: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    error: Optional[str] = None


def schedule_message(recipient: str, message: str, scheduled_time: str, media_path: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    """Schedule a WhatsApp message for future delivery.

    Args:
        recipient: Phone number or JID
        message: Message text
        scheduled_time: ISO 8601 formatted datetime string
        media_path: Optional path to media file

    Returns:
        Tuple of (success, status_message, scheduled_message_id)
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/schedule"
        payload = {
            "recipient": recipient,
            "message": message,
            "scheduled_time": scheduled_time
        }
        if media_path:
            payload["media_path"] = media_path

        response = requests.post(url, json=payload)
        result = response.json()

        if result.get("success", False):
            return True, result.get("message", "Scheduled successfully"), result.get("id")
        else:
            return False, result.get("message", "Unknown error"), None

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}", None
    except json.JSONDecodeError:
        return False, f"Error parsing response", None
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", None


def list_scheduled_messages(status: Optional[str] = None) -> List[dict]:
    """Get all scheduled messages, optionally filtered by status.

    Args:
        status: Optional filter - 'pending', 'sent', or 'failed'

    Returns:
        List of scheduled message dictionaries
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/schedule"
        params = {}
        if status:
            params["status"] = status

        response = requests.get(url, params=params)
        result = response.json()

        if result.get("success", False):
            return result.get("data", [])
        else:
            print(f"Error: {result.get('message', 'Unknown error')}")
            return []

    except requests.RequestException as e:
        print(f"Request error: {str(e)}")
        return []
    except json.JSONDecodeError:
        print(f"Error parsing response")
        return []
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return []


def cancel_scheduled_message(message_id: int) -> Tuple[bool, str]:
    """Cancel a pending scheduled message.

    Args:
        message_id: The ID of the scheduled message to cancel

    Returns:
        Tuple of (success, status_message)
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/schedule"
        params = {"id": message_id}

        response = requests.delete(url, params=params)
        result = response.json()

        return result.get("success", False), result.get("message", "Unknown error")

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# Channel watching functions

@dataclass
class WatchedChannel:
    jid: str
    name: str
    created_at: datetime


def watch_channel(jid: str, name: Optional[str] = None) -> Tuple[bool, str]:
    """Add a channel to the watch list.

    Args:
        jid: The JID of the channel to watch
        name: Optional name for the channel

    Returns:
        Tuple of (success, status_message)
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/watch"
        payload = {"jid": jid}
        if name:
            payload["name"] = name

        response = requests.post(url, json=payload)
        result = response.json()

        return result.get("success", False), result.get("message", "Unknown error")

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def unwatch_channel(jid: str) -> Tuple[bool, str]:
    """Remove a channel from the watch list.

    Args:
        jid: The JID of the channel to unwatch

    Returns:
        Tuple of (success, status_message)
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/watch"
        params = {"jid": jid}

        response = requests.delete(url, params=params)
        result = response.json()

        return result.get("success", False), result.get("message", "Unknown error")

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def list_watched_channels() -> dict:
    """Get all watched channels.

    Returns:
        Dictionary with channels list, count, and webhook_url
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/watch"
        response = requests.get(url)
        result = response.json()

        if result.get("success", False):
            return {
                "channels": result.get("channels", []),
                "count": result.get("count", 0),
                "webhook_url": result.get("webhook_url", "")
            }
        else:
            print(f"Error: {result.get('message', 'Unknown error')}")
            return {"channels": [], "count": 0, "webhook_url": ""}

    except requests.RequestException as e:
        print(f"Request error: {str(e)}")
        return {"channels": [], "count": 0, "webhook_url": ""}
    except json.JSONDecodeError:
        print(f"Error parsing response")
        return {"channels": [], "count": 0, "webhook_url": ""}
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return {"channels": [], "count": 0, "webhook_url": ""}


# Chat archive functions

def archive_chat(jid: str, archive: bool = True) -> Tuple[bool, str]:
    """Archive or unarchive a WhatsApp chat.

    Args:
        jid: The JID of the chat to archive/unarchive
        archive: True to archive, False to unarchive (default True)

    Returns:
        Tuple of (success, status_message)
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/archive"
        payload = {
            "jid": jid,
            "archive": archive
        }

        response = requests.post(url, json=payload)
        result = response.json()

        return result.get("success", False), result.get("message", "Unknown error")

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# Group member management functions

@dataclass
class GroupParticipant:
    jid: str
    name: Optional[str]
    is_admin: bool
    is_super_admin: bool


@dataclass
class GroupInfo:
    jid: str
    name: str
    topic: Optional[str]
    owner_jid: str
    created_at: Optional[str]
    participants: List[GroupParticipant]
    participant_count: int


def get_group_info(group_jid: str) -> dict:
    """Get information about a WhatsApp group including its members.

    Args:
        group_jid: The JID of the group (must end with @g.us)

    Returns:
        A dictionary containing group info and member list, or error information
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/group"
        params = {"jid": group_jid}

        response = requests.get(url, params=params)
        result = response.json()

        if result.get("success", False):
            return {
                "success": True,
                "jid": result.get("jid"),
                "name": result.get("name"),
                "topic": result.get("topic"),
                "owner_jid": result.get("owner_jid"),
                "created_at": result.get("created_at"),
                "participants": result.get("participants", []),
                "participant_count": result.get("participant_count", 0)
            }
        else:
            return {
                "success": False,
                "message": result.get("message", "Unknown error")
            }

    except requests.RequestException as e:
        return {
            "success": False,
            "message": f"Request error: {str(e)}"
        }
    except json.JSONDecodeError:
        return {
            "success": False,
            "message": "Error parsing response"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }


def add_group_members(group_jid: str, participants: List[str]) -> dict:
    """Add one or more members to a WhatsApp group.

    Args:
        group_jid: The JID of the group (must end with @g.us)
        participants: List of participant JIDs or phone numbers to add

    Returns:
        A dictionary containing success status and results for each participant
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/group/members"
        payload = {
            "group_jid": group_jid,
            "participants": participants
        }

        response = requests.post(url, json=payload)
        result = response.json()

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown error"),
            "group_jid": result.get("group_jid"),
            "results": result.get("results", [])
        }

    except requests.RequestException as e:
        return {
            "success": False,
            "message": f"Request error: {str(e)}"
        }
    except json.JSONDecodeError:
        return {
            "success": False,
            "message": "Error parsing response"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }


def remove_group_members(group_jid: str, participants: List[str]) -> dict:
    """Remove one or more members from a WhatsApp group.

    Args:
        group_jid: The JID of the group (must end with @g.us)
        participants: List of participant JIDs or phone numbers to remove

    Returns:
        A dictionary containing success status and results for each participant
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/group/members"
        payload = {
            "group_jid": group_jid,
            "participants": participants
        }

        response = requests.delete(url, json=payload)
        result = response.json()

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Unknown error"),
            "group_jid": result.get("group_jid"),
            "results": result.get("results", [])
        }

    except requests.RequestException as e:
        return {
            "success": False,
            "message": f"Request error: {str(e)}"
        }
    except json.JSONDecodeError:
        return {
            "success": False,
            "message": "Error parsing response"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }
