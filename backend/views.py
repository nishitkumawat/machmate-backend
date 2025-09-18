from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
import os
import gspread # type: ignore
from google.oauth2.service_account import Credentials
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from django.core.mail import send_mail

@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"detail": "CSRF cookie set"})


# Contact Us API
@api_view(["POST"])
@permission_classes([AllowAny])
def contact_view(request):
    try:
        name = request.data.get("name")
        email = request.data.get("email")
        subject = request.data.get("subject")
        message = request.data.get("message")

        if not all([name, email, subject, message]):
            return Response(
                {"error": "All fields are required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Load credentials from environment
        credentials_info = {
            "type": "service_account",
            "project_id": os.getenv("GCP_PROJECT_ID"),
            "private_key_id": os.getenv("GCP_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GCP_PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": os.getenv("GCP_CLIENT_EMAIL"),
            "client_id": os.getenv("GCP_CLIENT_ID"),
            "auth_uri": os.getenv("GCP_AUTH_URI"),
            "token_uri": os.getenv("GCP_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("GCP_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("GCP_CLIENT_X509_CERT_URL"),
        }

        # Use proper scopes for Sheets + Drive access
        creds = Credentials.from_service_account_info(
            credentials_info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )

        client = gspread.authorize(creds)

        # Open spreadsheet by URL
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/1bAz6nUzcl52dQT2jQAGRA9-64QpE4OHC-qMOVo2yHDI/edit"
        try:
            sheet = client.open_by_url(spreadsheet_url).sheet1
        except gspread.SpreadsheetNotFound:
            return Response(
                {"error": "Spreadsheet not found or service account lacks access."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Prepare data row
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        responded = "No"
        row = [name, email, subject, message, timestamp, responded]

        # Append row to sheet
        sheet.append_row(row)
        
        email_subject = f"Thank you for contacting MachMate"
        email_message = f"""
Hi {name},

Thank you for reaching out to us. We have received your message and will get back to you shortly.

Here’s a copy of your submission:

Subject: {subject}
Message: {message}

Best regards,
MachMate
"""
        send_mail(
            subject=email_subject,
            message=email_message,
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=[email],
            fail_silently=False,
        )

        return Response(
            {"success": True, "message": "Message saved successfully"}, 
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
