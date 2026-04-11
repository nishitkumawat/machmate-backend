import json
import cloudinary # type: ignore
import cloudinary.uploader  # type: ignore
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import connection
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status


# Helpers
def fetch_all(query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

def execute_query(query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        connection.commit()
        return cursor.lastrowid

# ----------------------------
# Maker Company Details
# ----------------------------
@csrf_exempt
@require_http_methods(["GET", "POST", "PUT"])
def maker_company_details(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method == "GET":
        query = """
            SELECT company_name, year_established, company_description, 
                   specializations, address, state, city, website
            FROM maker_company_details 
            WHERE maker_id = %s
        """
        result = fetch_all(query, [user_id])
        if result:
            result[0]["specializations"] = json.loads(result[0]["specializations"]) if result[0]["specializations"] else []
            return JsonResponse(result[0])
        else:
            return JsonResponse({"error": "Company profile not found"}, status=404)

    elif request.method in ["POST", "PUT"]:
        try:
            data = json.loads(request.body)

            required_fields = ['company_name', 'year_established', 'company_description',
                               'address', 'state', 'city']
            for field in required_fields:
                if field not in data or not data[field]:
                    return JsonResponse({"error": f"Missing required field: {field}"}, status=400)

            check_query = "SELECT id FROM maker_company_details WHERE maker_id = %s"
            existing = fetch_all(check_query, [user_id])

            specializations_json = json.dumps(data.get('specializations', []))

            if existing and request.method == "POST":
                return JsonResponse({"error": "Company details already exist. Use PUT to update."}, status=400)

            if existing:
                query = """
                    UPDATE maker_company_details 
                    SET company_name = %s, year_established = %s, company_description = %s,
                        specializations = %s, address = %s, state = %s, 
                        city = %s, website = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE maker_id = %s
                """
                params = [
                    data['company_name'], data['year_established'], data['company_description'],
                    specializations_json, data['address'], 
                    data['state'], data['city'], data.get('website'), user_id
                ]
            else:
                query = """
                    INSERT INTO maker_company_details 
                    (maker_id, company_name, year_established, company_description,
                     specializations, address, state, city, website)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = [
                    user_id, data['company_name'], data['year_established'], data['company_description'],
                    specializations_json, data['address'],
                    data['state'], data['city'], data.get('website')
                ]
            
            execute_query(query, params)
            return JsonResponse({"message": "Company details saved successfully"})

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# Open Projects for Makers
# ----------------------------
@csrf_exempt
@require_http_methods(["GET"])
def maker_open_projects(request):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        search_query = request.GET.get('search', '')
        price_filter = request.GET.get('price', '')
        date_filter = request.GET.get('date', '')

        base_query = """
                        SELECT 
                lw.work_id AS id, 
                lw.title AS name, 
                lw.description, 
                lw.estimated_price AS price,
                lw.estimated_date AS estimatedDate, 
                lw.address, 
                lw.state, 
                lw.city, 
                lw.pdf_report AS pdfUrl,
                lw.created_at,
                (SELECT COUNT(*) FROM quotation WHERE work_id = lw.work_id) AS quotation_count
            FROM listed_work lw
            WHERE lw.status = 'active'
            AND lw.work_id NOT IN (
                SELECT work_id FROM quotation WHERE maker_id = %s
            );

        """
        params = [user_id]

        if search_query:
            base_query += " AND (lw.title LIKE %s OR lw.description LIKE %s)"
            params.extend([f'%{search_query}%', f'%{search_query}%'])

        if price_filter == 'low':
            base_query += " ORDER BY lw.estimated_price ASC"
        elif price_filter == 'high':
            base_query += " ORDER BY lw.estimated_price DESC"
        elif date_filter == 'newest':
            base_query += " ORDER BY lw.created_at DESC"
        elif date_filter == 'oldest':
            base_query += " ORDER BY lw.created_at ASC"
        else:
            base_query += " ORDER BY lw.created_at DESC"

        projects = fetch_all(base_query, params)

        # 🔑 attach quotations for each project
        for project in projects:
            quotation_query = """
               SELECT 
                    q.quotation_id,
                    q.work_id,
                    q.maker_id,
                    q.description,
                    q.pdf_quotation,
                    q.price,
                    q.estimated_date,
                    q.status,
                    q.created_at,
                    u.name AS vendorName
                FROM quotation q
                LEFT JOIN users u ON q.maker_id = u.user_id
                WHERE q.work_id = %s;

            """
            quotations = fetch_all(quotation_query, [project["id"]])
            project["quotations"] = quotations

        return JsonResponse(projects, safe=False)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
@csrf_exempt
@require_http_methods(["POST"])
def create_quotation(request, project_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Default values
        amount = description = completion_date = None
        pdf_file = None

        if request.content_type and request.content_type.startswith("multipart/form-data"):
            amount = request.POST.get("amount")
            description = request.POST.get("description")
            completion_date = request.POST.get("completionDate")
            pdf_file = request.FILES.get("pdf")
        else:
            try:
                data = json.loads(request.body)
                amount = data.get("amount")
                description = data.get("description")
                completion_date = data.get("completionDate")
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON"}, status=400)

        # Validate required fields
        if not all([amount, description, completion_date]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        # Cast amount safely
        try:
            amount = float(amount)
        except ValueError:
            return JsonResponse({"error": "Amount must be a number"}, status=400)

        # Check if project exists
        project = fetch_all("SELECT work_id FROM listed_work WHERE work_id = %s", [project_id])
        if not project:
            return JsonResponse({"error": "Project not found"}, status=404)

        # Check duplicate quotation
        existing = fetch_all(
            "SELECT quotation_id FROM quotation WHERE maker_id = %s AND work_id = %s",
            [user_id, project_id]
        )
        if existing:
            return JsonResponse({"error": "You have already submitted a quotation for this project"}, status=400)

        # Upload PDF if provided
        pdf_url = ""
        if pdf_file:
            try:
                result = cloudinary.uploader.upload(pdf_file, resource_type="raw")
                pdf_url = result.get("secure_url", "")
            except Exception as e:
                return JsonResponse({"error": f"Failed to upload PDF: {str(e)}"}, status=500)

        # Insert into DB
        query = """
            INSERT INTO quotation 
            (work_id, maker_id, description, pdf_quotation, price, estimated_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = [project_id, user_id, description, pdf_url, amount, completion_date, "pending"]

        try:
            execute_query(query, params)
        except Exception as e:
            return JsonResponse({"error": f"Database error: {str(e)}"}, status=500)

        return JsonResponse({"message": "Quotation submitted successfully"}, status=201)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ----------------------------
# Maker's Quotations
# ----------------------------
@csrf_exempt
@require_http_methods(["GET"])
def maker_quotations(request):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        query = """
          SELECT 
    q.quotation_id, 
    q.work_id, 
    q.price,
    q.estimated_date, 
    q.status, 
    q.created_at,
    lw.title as project_name, 
    lw.description as project_description,
    lw.estimated_price as project_budget,
    u.name as buyer_name,
    q.pdf_quotation,
    lw.pdf_report, 
    q.description 
FROM quotation q
JOIN listed_work lw ON q.work_id = lw.work_id
JOIN users u ON lw.user_id = u.user_id
WHERE q.maker_id = %s
ORDER BY q.created_at DESC
        """
        quotations = fetch_all(query, [user_id])
        return JsonResponse(quotations, safe=False)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# CREATE OR UPDATE MAKER COMPANY PROFILE
# ----------------------------
@api_view(["POST", "PUT"])
def manage_company_profile(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)

    try:
        with connection.cursor() as cursor:
            # Check if user is a maker
            cursor.execute("SELECT role FROM users WHERE user_id=%s", [user_id])
            user = cursor.fetchone()
            
            if not user or user[0] != 'maker':
                return Response({"error": "User is not a maker"}, 
                               status=status.HTTP_403_FORBIDDEN)
            
            # Extract data from request
            company_name = request.data.get("company_name")
            year_established = request.data.get("year_established")
            company_description = request.data.get("company_description")
            specializations = request.data.get("specializations", [])
            address = request.data.get("address")
            state = request.data.get("state")
            city = request.data.get("city")
            website = request.data.get("website", "")
            
            # Validate required fields
            required_fields = {
                "company_name": company_name,
                "year_established": year_established,
                "company_description": company_description,
                "address": address,
                "state": state,
                "city": city
            }
            
            for field, value in required_fields.items():
                if not value:
                    return Response({"error": f"{field.replace('_', ' ').title()} is required"}, 
                                   status=status.HTTP_400_BAD_REQUEST)
            
            # Validate year
            try:
                year_int = int(year_established)
                if year_int < 1900 or year_int > 2023:
                    return Response({"error": "Year established must be between 1900 and 2023"}, 
                                   status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                return Response({"error": "Year established must be a valid number"}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            # Check if company profile already exists
            cursor.execute("SELECT id FROM maker_company_details WHERE maker_id=%s", [user_id])
            existing_company = cursor.fetchone()
            
            if request.method == "POST" and existing_company:
                return Response({"error": "Company profile already exists. Use PUT to update."}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            if request.method == "PUT" and not existing_company:
                return Response({"error": "Company profile not found. Use POST to create."}, 
                               status=status.HTTP_404_NOT_FOUND)
            
            # Convert specializations list to JSON string for database storage
            specializations_json = json.dumps(specializations) if specializations else "[]"
            
            if existing_company:
                # Update existing company profile
                cursor.execute("""
                    UPDATE maker_company_details 
                    SET company_name=%s, year_established=%s, company_description=%s,
                        specializations=%s, address=%s, state=%s, city=%s, website=%s,
                        updated_at=NOW()
                    WHERE maker_id=%s
                """, [
                    company_name, year_established, company_description,
                    specializations_json, address, state, city, website,
                    user_id
                ])
                
                message = "Company profile updated successfully"
            else:
                # Create new company profile
                cursor.execute("""
                    INSERT INTO maker_company_details 
                    (maker_id, company_name, year_established, company_description,
                     specializations, address, state, city, website, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """, [
                    user_id, company_name, year_established, company_description,
                    specializations_json, address, state, city, website
                ])
                
                message = "Company profile created successfully"
            
        return Response({"message": message}, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ----------------------------
# GET ALL MAKER PROFILES (for buyers to browse)
# ----------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def get_all_maker_profiles(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT mcd.id, mcd.maker_id, u.name, u.email, u.phone,
                       mcd.company_name, mcd.year_established, mcd.company_description,
                       mcd.specializations, mcd.address, mcd.state, mcd.city, mcd.website,
                       mcd.created_at
                FROM maker_company_details mcd
                JOIN users u ON mcd.maker_id = u.user_id
                ORDER BY mcd.created_at DESC
            """)
            
            makers = cursor.fetchall()
            
            maker_profiles = []
            for maker in makers:
                # Convert specializations from string to list
                specializations = []
                if maker[8]:
                    try:
                        specializations = json.loads(maker[8].replace("'", '"'))
                    except:
                        specializations = []
                
                maker_profiles.append({
                    "id": maker[0],
                    "maker_id": maker[1],
                    "maker_name": maker[2],
                    "email": maker[3],
                    "phone": maker[4],
                    "company_name": maker[5],
                    "year_established": maker[6],
                    "company_description": maker[7],
                    "specializations": specializations,
                    "address": maker[9],
                    "state": maker[10],
                    "city": maker[11],
                    "website": maker[12],
                    "joined_date": maker[13]
                })
            
        return Response(maker_profiles, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ----------------------------
# GET MAKER PROFILE BY ID
# ----------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def get_maker_profile_by_id(request, maker_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT mcd.id, mcd.maker_id, u.name, u.email, u.phone,
                       mcd.company_name, mcd.year_established, mcd.company_description,
                       mcd.specializations, mcd.address, mcd.state, mcd.city, mcd.website,
                       mcd.created_at
                FROM maker_company_details mcd
                JOIN users u ON mcd.maker_id = u.user_id
                WHERE mcd.maker_id = %s
            """, [maker_id])
            
            maker = cursor.fetchone()
            
            if not maker:
                return Response({"error": "Maker profile not found"}, 
                               status=status.HTTP_404_NOT_FOUND)
            
            # Convert specializations from string to list
            specializations = []
            if maker[8]:
                try:
                    specializations = json.loads(maker[8].replace("'", '"'))
                except:
                    specializations = []
            
            maker_profile = {
                "id": maker[0],
                "maker_id": maker[1],
                "maker_name": maker[2],
                "email": maker[3],
                "phone": maker[4],
                "company_name": maker[5],
                "year_established": maker[6],
                "company_description": maker[7],
                "specializations": specializations,
                "address": maker[9],
                "state": maker[10],
                "city": maker[11],
                "website": maker[12],
                "joined_date": maker[13]
            }
            
        return Response(maker_profile, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ----------------------------
# Product Details - Direct implementation
# ----------------------------
@csrf_exempt
@require_http_methods(["GET"])
def product_details(request, product_id):
    try:
        user_id = request.session.get("user_id")
        
        with connection.cursor() as cursor:
            # Get viewer's plan if logged in
            viewer_plan = "none"
            if user_id:
                cursor.execute("SELECT plan FROM users WHERE user_id = %s", [user_id])
                viewer_row = cursor.fetchone()
                if viewer_row:
                    viewer_plan = viewer_row[0]

            # Get product details with Uploader's info and Company details
            product_query = """
                SELECT 
                    lw.work_id AS id,
                    lw.title AS name,
                    lw.description,
                    lw.estimated_price AS price,
                    lw.estimated_date AS estimated_date,
                    COALESCE(lw.image_url, 'https://images.unsplash.com/photo-1581094794321-8411c1c0e0ce?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%%3D%%3D&auto=format&fit=crop&w=1000&q=80') AS image,
                    lw.pdf_report,
                    lw.city,
                    lw.state,
                    lw.created_at,
                    u.name AS uploaded_by_name,
                    u.user_id AS uploaded_by_id,
                    u.phone,
                    u.email,
                    COALESCE(u.plan, 'none') AS subscription_plan,
                    mcd.company_name,
                    mcd.address AS company_address,
                    mcd.city AS company_city,
                    mcd.state AS company_state,
                    mcd.website AS company_website
                FROM listed_work lw
                JOIN users u ON lw.user_id = u.user_id
                LEFT JOIN maker_company_details mcd ON u.user_id = mcd.maker_id
                WHERE lw.work_id = %s
            """
            cursor.execute(product_query, [product_id])
            product_rows = cursor.fetchall()
            
            if not product_rows:
                return JsonResponse({"error": "Product not found"}, status=404)
            
            # Convert to dict
            columns = [col[0] for col in cursor.description]
            product_data = dict(zip(columns, product_rows[0]))
            
            # Check if UPLOADER is premium (for other logic if needed, but requested logic is about VIEWER)
            uploader_is_premium = product_data.get("subscription_plan") == "premium"
            
            # Get quotations for this product
            quotations_query = """
                SELECT 
                    q.quotation_id AS id,
                    q.price AS amount,
                    q.description,
                    q.estimated_date AS completion_date,
                    q.pdf_quotation,
                    q.status,
                    q.created_at,
                    u.name AS vendor_name,
                    COALESCE(mcd.company_name, u.name) AS vendor_company
                FROM quotation q
                JOIN users u ON q.maker_id = u.user_id
                LEFT JOIN maker_company_details mcd ON q.maker_id = mcd.maker_id
                WHERE q.work_id = %s
                ORDER BY q.price ASC
            """
            cursor.execute(quotations_query, [product_id])
            quotation_rows = cursor.fetchall()
            quotation_columns = [col[0] for col in cursor.description]
            quotations = [dict(zip(quotation_columns, row)) for row in quotation_rows]
            
            # Get user's quotation if logged in
            user_quotation = None
            if user_id:
                user_quotation_query = """
                    SELECT 
                        quotation_id AS id,
                        price AS amount,
                        description,
                        estimated_date AS completion_date,
                        pdf_quotation,
                        status,
                        created_at
                    FROM quotation 
                    WHERE work_id = %s AND maker_id = %s
                """
                cursor.execute(user_quotation_query, [product_id, user_id])
                user_quotation_rows = cursor.fetchall()
                if user_quotation_rows:
                    user_quotation_columns = [col[0] for col in cursor.description]
                    user_quotation = dict(zip(user_quotation_columns, user_quotation_rows[0]))
        
        # Convert date objects to strings for JSON serialization
        estimated_date = product_data["estimated_date"]
        if hasattr(estimated_date, 'isoformat'):
            estimated_date = estimated_date.isoformat()
        
        response_data = {
            "id": product_data["id"],
            "name": product_data["name"],
            "description": product_data["description"],
            "price": float(product_data["price"]) if product_data["price"] else 0,
            "estimated_date": estimated_date,
            "image": product_data["image"],
            "pdf_report": product_data["pdf_report"],
            "city": product_data["city"],
            "state": product_data["state"],
            "uploaded_by_name": product_data["uploaded_by_name"],
            "is_premium_user": uploader_is_premium, # Kept for backward compatibility if frontend uses it
            "quotations": quotations,
            "user_quotation": user_quotation,
            "viewer_plan": viewer_plan # Helpful for frontend debugging
        }
        
        # Add Work Seeker Details IF Viewer is Premium
        if viewer_plan == "premium":
            response_data["work_seeker_details"] = {
                "display_name": product_data["uploaded_by_name"],
                "company_name": product_data["company_name"],
                "company_address": product_data["company_address"],
                "company_city": product_data["company_city"],
                "company_state": product_data["company_state"],
                "phone_number": product_data["phone"],
                "email": product_data["email"],
                "website": product_data["company_website"]
            }
        
        # Legacy support: old logic added phone/email if UPLOADER was premium. 
        # The request specifically asks for "only for plan = premium user" (implies viewer).
        # I'll keep the response_data clean and use `work_seeker_details` key.
        
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in product_details: {str(e)}")
        print(f"Traceback: {error_details}")
        return JsonResponse({"error": f"Server error: {str(e)}"}, status=500)

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_quotation(request, quotation_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Check if quotation exists and belongs to user
        quotation_query = """
            SELECT quotation_id FROM quotation 
            WHERE quotation_id = %s AND maker_id = %s
        """
        quotation_result = fetch_all(quotation_query, [quotation_id, user_id])
        
        if not quotation_result:
            return JsonResponse({"error": "Quotation not found or access denied"}, status=404)

        # Delete quotation
        delete_query = "DELETE FROM quotation WHERE quotation_id = %s AND maker_id = %s"
        execute_query(delete_query, [quotation_id, user_id])

        return JsonResponse({"message": "Quotation deleted successfully"})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)