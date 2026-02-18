import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger

from app.config import settings

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


class EmailService:
    """
    Gmail SMTP email service using App Password authentication.
    Sends via smtp.gmail.com:587 with STARTTLS.
    """

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self):
        self.gmail_address = settings.GMAIL_ADDRESS
        self.gmail_app_password = settings.GMAIL_APP_PASSWORD.replace(" ", "")
        self.from_name = settings.EMAIL_FROM_NAME
        self.dashboard_url = settings.DASHBOARD_URL

    # ------------------------------------------------------------------ #
    #  Core send method                                                    #
    # ------------------------------------------------------------------ #

    async def _send(self, to_email: str, subject: str, html_body: str) -> None:
        """Build a MIME email and send it via Gmail SMTP with STARTTLS."""
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{self.from_name} <{self.gmail_address}>"
        message["To"] = to_email

        message.attach(MIMEText(subject, "plain"))
        message.attach(MIMEText(html_body, "html"))

        try:
            await aiosmtplib.send(
                message,
                hostname=self.SMTP_HOST,
                port=self.SMTP_PORT,
                username=self.gmail_address,
                password=self.gmail_app_password,
                start_tls=True,
            )
            logger.info(f"Email sent to {to_email} | Subject: {subject}")
        except aiosmtplib.SMTPException as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            raise

    def _render(self, template_name: str, **context) -> str:
        """Render a Jinja2 HTML template with the given context variables."""
        template = jinja_env.get_template(f"emails/{template_name}")
        return template.render(**context)

    # ------------------------------------------------------------------ #
    #  Public email methods                                                #
    # ------------------------------------------------------------------ #

    async def send_pharmacy_welcome(
        self,
        to_email: str,
        pharmacy_name: str,
        contact_name: str,
        temp_password: str,
        login_url: Optional[str] = None,
    ) -> None:
        """Send welcome email to a newly registered pharmacy with their login credentials."""
        html = self._render(
            "pharmacy_welcome.html",
            subject="Welcome to RERUN Health — Your Login Details",
            contact_name=contact_name,
            pharmacy_name=pharmacy_name,
            email=to_email,
            temp_password=temp_password,
            login_url=login_url or self.dashboard_url,
        )
        await self._send(
            to_email=to_email,
            subject=f"Welcome to RERUN Health — {pharmacy_name}",
            html_body=html,
        )

    async def send_password_reset(
        self,
        to_email: str,
        contact_name: str,
        temp_password: str,
    ) -> None:
        """Send a password reset email with a new temporary password."""
        html = self._render(
            "password_reset.html",
            subject="RERUN Health — Password Reset",
            contact_name=contact_name,
            email=to_email,
            temp_password=temp_password,
            login_url=self.dashboard_url,
        )
        await self._send(
            to_email=to_email,
            subject="RERUN Health — Your Password Has Been Reset",
            html_body=html,
        )

    async def send_admin_notification(
        self,
        subject: str,
        message: str,
        details: Optional[dict] = None,
    ) -> None:
        """Send an admin notification email to the configured Gmail address."""
        html = self._render(
            "admin_notification.html",
            subject=subject,
            message=message,
            details=details or {},
        )
        await self._send(
            to_email=self.gmail_address,
            subject=f"[RERUN Admin] {subject}",
            html_body=html,
        )

    async def send_customer_notification(
        self,
        to_email: str,
        message: str,
        customer_name: Optional[str] = None,
        cta_text: Optional[str] = None,
        cta_url: Optional[str] = None,
    ) -> None:
        """Send a general notification email to a customer."""
        html = self._render(
            "customer_notification.html",
            subject="A message from RERUN Health",
            customer_name=customer_name,
            message=message,
            cta_text=cta_text,
            cta_url=cta_url,
        )
        await self._send(
            to_email=to_email,
            subject="RERUN Health — Update for You",
            html_body=html,
        )


email_service = EmailService()
