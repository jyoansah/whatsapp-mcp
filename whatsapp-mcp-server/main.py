from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_direct_chat_by_contact as whatsapp_get_direct_chat_by_contact,
    get_contact_chats as whatsapp_get_contact_chats,
    get_last_interaction as whatsapp_get_last_interaction,
    get_message_context as whatsapp_get_message_context,
    send_message as whatsapp_send_message,
    send_reply as whatsapp_send_reply,
    send_file as whatsapp_send_file,
    send_audio_message as whatsapp_audio_voice_message,
    download_media as whatsapp_download_media,
    schedule_message as whatsapp_schedule_message,
    list_scheduled_messages as whatsapp_list_scheduled_messages,
    cancel_scheduled_message as whatsapp_cancel_scheduled_message,
    watch_channel as whatsapp_watch_channel,
    unwatch_channel as whatsapp_unwatch_channel,
    list_watched_channels as whatsapp_list_watched_channels,
    archive_chat as whatsapp_archive_chat
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.
    
    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    return contacts

@mcp.tool()
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
) -> List[Dict[str, Any]]:
    """Get WhatsApp messages matching specified criteria with optional context.
    
    Args:
        after: Optional ISO-8601 formatted string to only return messages after this date
        before: Optional ISO-8601 formatted string to only return messages before this date
        sender_phone_number: Optional phone number to filter messages by sender
        chat_jid: Optional chat JID to filter messages by chat
        query: Optional search term to filter messages by content
        limit: Maximum number of messages to return (default 20)
        page: Page number for pagination (default 0)
        include_context: Whether to include messages before and after matches (default True)
        context_before: Number of messages to include before each match (default 1)
        context_after: Number of messages to include after each match (default 1)
    """
    messages = whatsapp_list_messages(
        after=after,
        before=before,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid,
        query=query,
        limit=limit,
        page=page,
        include_context=include_context,
        context_before=context_before,
        context_after=context_after
    )
    return messages

@mcp.tool()
def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats matching specified criteria.
    
    Args:
        query: Optional search term to filter chats by name or JID
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
        include_last_message: Whether to include the last message in each chat (default True)
        sort_by: Field to sort results by, either "last_active" or "name" (default "last_active")
    """
    chats = whatsapp_list_chats(
        query=query,
        limit=limit,
        page=page,
        include_last_message=include_last_message,
        sort_by=sort_by
    )
    return chats

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.
    
    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return chat

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.
    
    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return chat

@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.
    
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    chats = whatsapp_get_contact_chats(jid, limit, page)
    return chats

@mcp.tool()
def get_last_interaction(jid: str) -> str:
    """Get most recent WhatsApp message involving the contact.
    
    Args:
        jid: The JID of the contact to search for
    """
    message = whatsapp_get_last_interaction(jid)
    return message

@mcp.tool()
def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> Dict[str, Any]:
    """Get context around a specific WhatsApp message.
    
    Args:
        message_id: The ID of the message to get context for
        before: Number of messages to include before the target message (default 5)
        after: Number of messages to include after the target message (default 5)
    """
    context = whatsapp_get_message_context(message_id, before, after)
    return context

@mcp.tool()
def send_message(
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. For group chats use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send
    
    Returns:
        A dictionary containing success status and a status message
    """
    # Validate input
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }
    
    # Call the whatsapp_send_message function with the unified recipient parameter
    success, status_message = whatsapp_send_message(recipient, message)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_reply(
    recipient: str,
    message: str,
    reply_to_id: str,
    reply_to_jid: str
) -> Dict[str, Any]:
    """Send a WhatsApp message as a reply to a specific message.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send
        reply_to_id: The ID of the message being replied to (from the message's 'id' field)
        reply_to_jid: The JID of the sender of the message being replied to (from the message's 'sender' field,
                     should be in format "123456789@s.whatsapp.net")

    Returns:
        A dictionary containing success status and a status message
    """
    # Validate input
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }

    if not reply_to_id:
        return {
            "success": False,
            "message": "reply_to_id must be provided"
        }

    # Call the whatsapp_send_reply function
    success, status_message = whatsapp_send_reply(recipient, message, reply_to_id, reply_to_jid)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file such as a picture, raw audio, video or document via WhatsApp to the specified recipient. For group messages use the JID.
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the media file to send (image, video, document)
    
    Returns:
        A dictionary containing success status and a status message
    """
    
    # Call the whatsapp_send_file function
    success, status_message = whatsapp_send_file(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send any audio file as a WhatsApp audio message to the specified recipient. For group messages use the JID. If it errors due to ffmpeg not being installed, use send_file instead.
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the audio file to send (will be converted to Opus .ogg if it's not a .ogg file)
    
    Returns:
        A dictionary containing success status and a status message
    """
    success, status_message = whatsapp_audio_voice_message(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def download_media(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download media from a WhatsApp message and get the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        A dictionary containing success status, a status message, and the file path if successful
    """
    result = whatsapp_download_media(message_id, chat_jid)
    return result

@mcp.tool()
def schedule_message(
    recipient: str,
    message: str,
    scheduled_time: str,
    media_path: Optional[str] = None
) -> Dict[str, Any]:
    """Schedule a WhatsApp message for future delivery.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send
        scheduled_time: When to send the message in ISO 8601 format (e.g., "2024-12-25T10:00:00Z")
        media_path: Optional absolute path to a media file to send with the message

    Returns:
        A dictionary containing success status, a status message, and the scheduled message ID
    """
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }

    if not message and not media_path:
        return {
            "success": False,
            "message": "Message or media_path must be provided"
        }

    success, status_message, message_id = whatsapp_schedule_message(
        recipient, message, scheduled_time, media_path
    )

    result = {
        "success": success,
        "message": status_message
    }
    if message_id:
        result["scheduled_message_id"] = message_id

    return result

@mcp.tool()
def list_scheduled_messages(status: Optional[str] = None) -> Dict[str, Any]:
    """List all scheduled WhatsApp messages.

    Args:
        status: Optional filter by status - "pending", "sent", or "failed"

    Returns:
        A dictionary containing the list of scheduled messages and count
    """
    messages = whatsapp_list_scheduled_messages(status)
    return {
        "success": True,
        "messages": messages,
        "count": len(messages)
    }

@mcp.tool()
def cancel_scheduled_message(message_id: int) -> Dict[str, Any]:
    """Cancel a pending scheduled WhatsApp message.

    Args:
        message_id: The ID of the scheduled message to cancel

    Returns:
        A dictionary containing success status and a status message
    """
    success, status_message = whatsapp_cancel_scheduled_message(message_id)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def watch_channel(jid: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Add a WhatsApp channel/chat to the watch list. Messages from watched channels trigger webhooks to the configured WHATSAPP_WEBHOOK_URL.

    Args:
        jid: The JID of the channel to watch (e.g., "123456789@s.whatsapp.net" or group JID)
        name: Optional friendly name for the channel

    Returns:
        A dictionary containing success status and a status message
    """
    if not jid:
        return {
            "success": False,
            "message": "JID must be provided"
        }

    success, status_message = whatsapp_watch_channel(jid, name)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def unwatch_channel(jid: str) -> Dict[str, Any]:
    """Remove a WhatsApp channel/chat from the watch list.

    Args:
        jid: The JID of the channel to stop watching

    Returns:
        A dictionary containing success status and a status message
    """
    if not jid:
        return {
            "success": False,
            "message": "JID must be provided"
        }

    success, status_message = whatsapp_unwatch_channel(jid)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def list_watched_channels() -> Dict[str, Any]:
    """List all WhatsApp channels/chats being watched for webhook notifications.

    Returns:
        A dictionary containing the list of watched channels, count, and configured webhook URL
    """
    result = whatsapp_list_watched_channels()
    return {
        "success": True,
        "channels": result.get("channels", []),
        "count": result.get("count", 0),
        "webhook_url": result.get("webhook_url", "")
    }

@mcp.tool()
def archive_chat(jid: str, archive: bool = True) -> Dict[str, Any]:
    """Archive or unarchive a WhatsApp chat. Archiving a chat will hide it from the main chat list. Note: Archiving a chat will also unpin it if it was pinned.

    Args:
        jid: The JID of the chat to archive/unarchive (e.g., "123456789@s.whatsapp.net" or group JID like "123456789@g.us")
        archive: True to archive the chat, False to unarchive (default True)

    Returns:
        A dictionary containing success status and a status message
    """
    if not jid:
        return {
            "success": False,
            "message": "JID must be provided"
        }

    success, status_message = whatsapp_archive_chat(jid, archive)
    return {
        "success": success,
        "message": status_message
    }

if __name__ == "__main__":
    import os
    # Initialize and run the server
    transport = os.environ.get('MCP_TRANSPORT', 'stdio')
    port = int(os.environ.get('MCP_PORT', '8000'))
    if transport == 'sse':
        import uvicorn
        uvicorn.run(mcp.sse_app(), host='0.0.0.0', port=port)
    else:
        mcp.run(transport='stdio')