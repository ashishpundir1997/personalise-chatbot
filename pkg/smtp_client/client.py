import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTPSenderRefused, SMTPServerDisconnected
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    smtp_server: str
    smtp_port: int
    username: str
    password: str
    use_tls: bool = True
    max_retries: int = 3


class EmailError(Exception):
    """Base exception for email-related errors"""

    pass


class EmailClient:
    def __init__(self, config: EmailConfig) -> None:
        self.config = config
        self._server: smtplib.SMTP | None = None

    def connect(self) -> None:
        """Establish connection to SMTP server"""
        try:
            if self._server:
                try:
                    self._server.quit()
                except Exception:
                    pass

            self._server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port)
            if self.config.use_tls:
                self._server.starttls()
            
            # Check if credentials are provided
            if not self.config.username or not self.config.password:
                raise EmailError(
                    "SMTP credentials not configured. Please set SMTP_USERNAME and SMTP_PASSWORD environment variables."
                )
            
            self._server.login(self.config.username, self.config.password)
        except smtplib.SMTPAuthenticationError as e:
            self._server = None
            error_msg = str(e)
            if "BadCredentials" in error_msg or "535" in error_msg:
                raise EmailError(
                    f"Gmail authentication failed. Please ensure:\n"
                    f"1. You're using a Gmail App Password (not your regular password)\n"
                    f"2. 2-Step Verification is enabled on your Google account\n"
                    f"3. You've generated an App Password at: https://myaccount.google.com/apppasswords\n"
                    f"4. The App Password is correctly set in the SMTP_PASSWORD environment variable\n"
                    f"Original error: {error_msg}"
                )
            raise EmailError(f"Failed to authenticate with SMTP server: {error_msg}")
        except Exception as e:
            self._server = None
            raise EmailError(f"Failed to connect to SMTP server: {e!s}")

    def ensure_connection(self) -> None:
        """Ensure SMTP connection is active, reconnect if needed"""
        if not self._server:
            self.connect()
            return

        try:
            # Try to verify connection is still alive
            status = self._server.noop()[0]
            if status != 250:
                self.connect()
        except Exception:
            self.connect()

    async def send_email(
        self,
        to_addresses: list[str],
        subject: str,
        body: str = "",
        from_address: str = "no-reply@mipal.ai",
        html_content: str | None = None,
    ) -> None:
        """Send email to specified recipients with automatic retry on failure"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = ", ".join(to_addresses)
        msg.attach(MIMEText(body, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

        loop = asyncio.get_event_loop()
        
        for attempt in range(self.config.max_retries):
            try:
                # Run blocking operations in executor to avoid blocking event loop
                await loop.run_in_executor(None, self.ensure_connection)
                await loop.run_in_executor(None, self._server.send_message, msg)
                return
            except SMTPServerDisconnected:
                logger.warning("SMTP server disconnected. Attempting to reconnect...")
                if attempt == self.config.max_retries - 1:
                    raise EmailError(
                        "Failed to maintain SMTP connection after multiple attempts"
                    )
            except SMTPSenderRefused as e:
                logger.error(f"SMTP sender refused: {e!s}")
                raise EmailError(f"Email sending refused by server: {e!s}")
            except Exception as e:
                logger.error(f"Failed to send email (attempt {attempt + 1}): {e!s}")
                if attempt == self.config.max_retries - 1:
                    raise EmailError(
                        f"Failed to send email after {self.config.max_retries} attempts: {e!s}"
                    )

    def close(self) -> None:
        """Close SMTP connection"""
        if self._server:
            try:
                self._server.quit()
            except Exception as e:
                logger.warning(f"Error while closing SMTP connection: {e!s}")
            finally:
                self._server = None

    def __enter__(self) -> "EmailClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        self.close()