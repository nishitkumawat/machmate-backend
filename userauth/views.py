import re
from django.db import connection
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status


# ✅ REGISTER VIEW
@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    name = request.data.get("name")
    email = request.data.get("email")
    password = request.data.get("password")
    phone = request.data.get("phone")
    role = request.data.get("accountType", "buyer")  # default is user

    if not name or not email or not password or not phone:
        return Response({"error": "name, email, phone, and password are required"},
                        status=status.HTTP_400_BAD_REQUEST)

    # ✅ Password validation
    if len(password) < 8:
        return Response({"error": "Password must be at least 8 characters"},
                        status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[A-Z]", password):
        return Response({"error": "Password must contain at least one uppercase"},
                        status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[@$!%*?&]", password):
        return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                        status=status.HTTP_400_BAD_REQUEST)

    # ✅ Phone validation
    if not re.fullmatch(r"\d{10}", phone):
        return Response({"error": "Phone must be 10 digits"},
                        status=status.HTTP_400_BAD_REQUEST)

    if role not in ["buyer", "maker"]:
        return Response({"error": "Invalid role"},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Check if user already exists
            cursor.execute("SELECT user_id FROM users WHERE name=%s OR email=%s OR phone=%s",
                           [name, email, phone])
            if cursor.fetchone():
                return Response({"error": "name, email or phone already exists"},
                                status=status.HTTP_400_BAD_REQUEST)

            # Hash password
            hashed_pw = make_password(password)

            # Insert user
            cursor.execute(
                "INSERT INTO users (name, email, phone, password, role) VALUES (%s, %s, %s, %s, %s)",
                [name, email, phone, hashed_pw, role]
            )

        return Response({"message": "User registered successfully", "role": role},
                        status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ✅ LOGIN VIEW
@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get("email")
    password = request.data.get("password")
    remember_me = request.data.get("remember_me", False)

    if not email or not password:
        return Response({"error": "Please provide email and password"},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id, password, role FROM users WHERE email=%s", [email])
            user = cursor.fetchone()

            if not user:
                return Response({"error": "Invalid email or password"},
                                status=status.HTTP_401_UNAUTHORIZED)

            user_id, stored_password, role = user

            if not check_password(password, stored_password):
                return Response({"error": "Invalid email or password"},
                                status=status.HTTP_401_UNAUTHORIZED)

            # ✅ Session Handling
            request.session["user_id"] = user_id
            request.session["role"] = role

            if remember_me:
                request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
            else:
                request.session.set_expiry(0)  # expire on browser close

        return Response({
            "message": "Login successful",
            "email": email,
            "role": role
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ✅ LOGOUT VIEW
@api_view(["POST"])
def logout_view(request):
    try:
        request.session.flush()
        return Response({"message": "Logged out successfully"},
                        status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ WHO AM I VIEW
@api_view(["GET"])
def me_view(request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id:
        return Response({"isAuthenticated": False}, status=status.HTTP_200_OK)

    return Response({
        "isAuthenticated": True,
        "user_id": user_id,
        "role": role
    }, status=status.HTTP_200_OK)

import re
from django.db import connection
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

# ✅ GET USER PROFILE
@api_view(["GET"])
def get_user_profile(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name, email, phone, role FROM users WHERE user_id=%s", 
                [user_id]
            )
            user = cursor.fetchone()
            
            if not user:
                return Response({"error": "User not found"}, 
                               status=status.HTTP_404_NOT_FOUND)
            
            # Convert to dictionary
            user_data = {
                "user_id": user[0],
                "name": user[1],
                "email": user[2],
                "phone": user[3],
                "role": user[4]
            }
            
        return Response(user_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ UPDATE USER PROFILE
@api_view(["PUT"])
def update_user_profile(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)
    
    name = request.data.get("name")
    phone = request.data.get("phone")
    current_password = request.data.get("currentPassword")
    new_password = request.data.get("newPassword")
    confirm_password = request.data.get("confirmPassword")
    
    # Validate required fields
    if not name or not phone:
        return Response({"error": "Name and phone are required"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Validate phone format
    if not re.fullmatch(r"\d{10}", phone):
        return Response({"error": "Phone must be 10 digits"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Check if password change is requested
    changing_password = bool(current_password or new_password or confirm_password)
    
    if changing_password:
        if not current_password or not new_password or not confirm_password:
            return Response({"error": "All password fields are required for password change"}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        if new_password != confirm_password:
            return Response({"error": "New passwords do not match"}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        # Password validation
        if len(new_password) < 8:
            return Response({"error": "Password must be at least 8 characters"},
                           status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[A-Z]", new_password):
            return Response({"error": "Password must contain at least one uppercase letter"},
                           status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[@$!%*?&]", new_password):
            return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                           status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Check if phone is already taken by another user
            cursor.execute(
                "SELECT user_id FROM users WHERE phone=%s AND user_id != %s", 
                [phone, user_id]
            )
            if cursor.fetchone():
                return Response({"error": "Phone number already in use"}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            # Verify current password if changing password
            if changing_password:
                cursor.execute(
                    "SELECT password FROM users WHERE user_id=%s", 
                    [user_id]
                )
                result = cursor.fetchone()
                
                if not result or not check_password(current_password, result[0]):
                    return Response({"error": "Current password is incorrect"}, 
                                   status=status.HTTP_400_BAD_REQUEST)
                
                # Update with password change
                hashed_password = make_password(new_password)
                cursor.execute(
                    "UPDATE users SET name=%s, phone=%s, password=%s WHERE user_id=%s",
                    [name, phone, hashed_password, user_id]
                )
            else:
                # Update without password change
                cursor.execute(
                    "UPDATE users SET name=%s, phone=%s WHERE user_id=%s",
                    [name, phone, user_id]
                )
            
        return Response({"message": "Profile updated successfully"}, 
                       status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ CHANGE PASSWORD ONLY
@api_view(["POST"])
def change_password(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)
    
    current_password = request.data.get("currentPassword")
    new_password = request.data.get("newPassword")
    confirm_password = request.data.get("confirmPassword")
    
    if not current_password or not new_password or not confirm_password:
        return Response({"error": "All password fields are required"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    if new_password != confirm_password:
        return Response({"error": "New passwords do not match"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Password validation
    if len(new_password) < 8:
        return Response({"error": "Password must be at least 8 characters"},
                       status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[A-Z]", new_password):
        return Response({"error": "Password must contain at least one uppercase letter"},
                       status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[@$!%*?&]", new_password):
        return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                       status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Verify current password
            cursor.execute(
                "SELECT password FROM users WHERE user_id=%s", 
                [user_id]
            )
            result = cursor.fetchone()
            
            if not result or not check_password(current_password, result[0]):
                return Response({"error": "Current password is incorrect"}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            # Update password
            hashed_password = make_password(new_password)
            cursor.execute(
                "UPDATE users SET password=%s WHERE user_id=%s",
                [hashed_password, user_id]
            )
            
        return Response({"message": "Password changed successfully"}, 
                       status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)