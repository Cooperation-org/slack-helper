"""
Slack Bot Service - Handle slash commands and events
"""

import logging
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from src.services.qa_service import QAService
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

class SlackBotService:
    def __init__(self, bot_token: str, app_token: str, signing_secret: str):
        self.app = AsyncApp(
            token=bot_token,
            signing_secret=signing_secret
        )
        self.app_token = app_token
        self.qa_service = QAService()
        self._setup_commands()
    
    def _setup_commands(self):
        """Setup slash commands"""
        
        @self.app.command("/ask")
        async def handle_ask_command(ack, respond, command):
            await ack()
            
            try:
                question = command['text'].strip()
                if not question:
                    await respond("Please provide a question. Usage: `/ask your question here`")
                    return
                
                # Get workspace info
                workspace_id = command['team_id']
                user_id = command['user_id']
                
                # Get Q&A response
                response = await self.qa_service.ask_question(
                    question=question,
                    workspace_id=workspace_id,
                    include_documents=True,
                    include_slack=True,
                    max_sources=5
                )
                
                # Format response for Slack
                blocks = self._format_qa_response(response, question)
                await respond(blocks=blocks)
                
            except Exception as e:
                logger.error(f"Error in /ask command: {e}")
                await respond(f"Sorry, I encountered an error: {str(e)}")
        
        @self.app.command("/askall")
        async def handle_askall_command(ack, respond, command):
            await ack()
            
            try:
                question = command['text'].strip()
                if not question:
                    await respond("Please provide a question. Usage: `/askall your question here`")
                    return
                
                # Get workspace info
                workspace_id = command['team_id']
                
                # Get Q&A response (search all workspaces for this org)
                response = await self.qa_service.ask_question(
                    question=question,
                    workspace_id=None,  # Search all workspaces
                    include_documents=True,
                    include_slack=True,
                    max_sources=10
                )
                
                # Format response for Slack
                blocks = self._format_qa_response(response, question, is_global=True)
                await respond(blocks=blocks)
                
            except Exception as e:
                logger.error(f"Error in /askall command: {e}")
                await respond(f"Sorry, I encountered an error: {str(e)}")
    
    def _format_qa_response(self, response: dict, question: str, is_global: bool = False) -> list:
        """Format Q&A response for Slack blocks"""
        
        scope = "all workspaces" if is_global else "this workspace"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Question:* {question}"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Answer* (searched {scope}):\n{response['answer']}"
                }
            }
        ]
        
        # Add confidence if available
        if response.get('confidence'):
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Confidence: {response['confidence']}%"
                    }
                ]
            })
        
        # Add sources if available
        sources = response.get('sources', [])
        if sources:
            source_text = "*Sources:*\n"
            for i, source in enumerate(sources[:3], 1):  # Limit to 3 sources
                if source.get('channel_name'):
                    source_text += f"{i}. #{source['channel_name']} - {source.get('user_name', 'Unknown')}\n"
                elif source.get('filename'):
                    source_text += f"{i}. Document: {source['filename']}\n"
                else:
                    source_text += f"{i}. {source.get('source_type', 'Unknown source')}\n"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": source_text
                }
            })
        
        return blocks
    
    async def start(self):
        """Start the Slack bot"""
        handler = AsyncSocketModeHandler(self.app, self.app_token)
        await handler.start_async()
        logger.info("Slack bot started and listening for commands")
    
    async def stop(self):
        """Stop the Slack bot"""
        # Cleanup if needed
        pass


async def start_slack_bot_for_workspace(workspace_id: str):
    """Start Slack bot for a specific workspace"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Get credentials for workspace
        cursor.execute("""
            SELECT bot_token, app_token, signing_secret 
            FROM installations 
            WHERE workspace_id = %s
        """, (workspace_id,))
        
        result = cursor.fetchone()
        if not result:
            logger.error(f"No credentials found for workspace {workspace_id}")
            return None
        
        bot_token, app_token, signing_secret = result
        
        # Create and start bot service
        bot_service = SlackBotService(bot_token, app_token, signing_secret)
        await bot_service.start()
        
        logger.info(f"Slack bot started for workspace {workspace_id}")
        return bot_service
        
    except Exception as e:
        logger.error(f"Error starting Slack bot for workspace {workspace_id}: {e}")
        return None
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)