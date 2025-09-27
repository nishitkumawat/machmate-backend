from datetime import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
import json
from django.views.decorators.http import require_http_methods


# Helper to execute SELECT queries
def fetch_all(query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

# Helper to execute INSERT/UPDATE/DELETE
def execute_query(query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        connection.commit()
        return cursor.lastrowid

def get_projects(request):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        query = """
            SELECT work_id AS id,
                   title AS name,
                   description,
                   estimated_price AS minPrice,
                   estimated_price AS maxPrice,
                   estimated_date AS estimatedDate,
                   address,
                   state,
                   city,
                   pdf_report AS pdfUrl,
                   status
            FROM listed_work
            WHERE user_id=%s AND status='Active'
        """
        projects = fetch_all(query, [user_id])
        return JsonResponse(projects, safe=False)
    except Exception as e:
        print("Error in get_projects:", e)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def create_project(request):
    if request.method == "POST":
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Access form fields
        name = request.POST.get("name")
        description = request.POST.get("description")
        maxPrice = request.POST.get("maxPrice")
        estimatedDate = request.POST.get("estimatedDate")
        address = request.POST.get("address")
        state = request.POST.get("state")
        city = request.POST.get("city")

        # Handle PDF upload if provided
        pdf_file = request.FILES.get("pdf")
        pdf_url = ""
        if pdf_file:
            result = cloudinary.uploader.upload(
                pdf_file,
                resource_type="raw"  # Required for PDF/other non-image files
            )
            pdf_url = result.get("secure_url", "")

        query = """
            INSERT INTO listed_work
            (user_id, title, description, estimated_price, estimated_date, address, state, city, pdf_report)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_query(query, [user_id, name, description, maxPrice, estimatedDate, address, state, city, pdf_url])

        return JsonResponse({"message": "Project created", "pdf_url": pdf_url}, status=201)


@csrf_exempt
def update_project(request, project_id):
    if request.method == "POST":  # Changed from PUT to POST
        try:
            # Now request.POST will be populated automatically
            name = request.POST.get("name")
            description = request.POST.get("description")
            maxPrice = request.POST.get("maxPrice")
            estimatedDate = request.POST.get("estimatedDate")
            address = request.POST.get("address")
            state = request.POST.get("state")
            city = request.POST.get("city")
            
            # Handle file upload if present
            pdf_url = None
            if 'pdf' in request.FILES:
                pdf_file = request.FILES['pdf']
                # Upload to Cloudinary like in create_project
                result = cloudinary.uploader.upload(
                    pdf_file,
                    resource_type="raw"  # Required for PDF/other non-image files
                )
                pdf_url = result.get("secure_url", "")
            
            # Build the SQL query based on whether we have a new PDF
            if pdf_url:
                query = """
                    UPDATE listed_work
                    SET title=%s, description=%s, estimated_price=%s, estimated_date=%s,
                        address=%s, state=%s, city=%s, pdf_report=%s
                    WHERE work_id=%s
                """
                params = [
                    name, description, maxPrice, estimatedDate, 
                    address, state, city, pdf_url, project_id
                ]
            else:
                query = """
                    UPDATE listed_work
                    SET title=%s, description=%s, estimated_price=%s, estimated_date=%s,
                        address=%s, state=%s, city=%s
                    WHERE work_id=%s
                """
                params = [
                    name, description, maxPrice, estimatedDate, 
                    address, state, city, project_id
                ]
            
            # Validate required fields
            if not all([name, description, maxPrice, estimatedDate]):
                return JsonResponse({"error": "Missing required fields"}, status=400)
            
            execute_query(query, params)
            return JsonResponse({"message": "Project updated"}, status=200)
            
        except Exception as e:
            import traceback
            print("Error in update_project:", traceback.format_exc())
            return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# Completed Orders (completed_work)
# ----------------------------
def get_completed_orders(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    query = """
        SELECT 
            cw.completed_work_id AS completedId,
            cw.price AS amount,
            cw.completion_date AS completionDate,
            cw.pdf_report AS report,
            cw.title AS projectName,
            cw.description AS projectDescription,
            cw.created_at AS workCreatedAt,

            -- Quotation details
            q.quotation_id AS quotationId,
            q.price AS quotationAmount,
            q.description AS quotationMessage,
            q.created_at AS quotationCreatedAt,

            -- Maker details
            maker.user_id AS makerId,
            maker.name AS makerName,
            maker.email AS makerEmail,

            -- Buyer details
            buyer.user_id AS buyerId,
            buyer.name AS buyerName,
            buyer.email AS buyerEmail

        FROM completed_work cw
        JOIN users maker ON cw.maker_id = maker.user_id
        JOIN users buyer ON cw.user_id = buyer.user_id
        LEFT JOIN quotation q ON cw.quotation_id = q.quotation_id
        WHERE cw.user_id = %s
    """

    orders = fetch_all(query, [user_id])
    return JsonResponse(orders, safe=False)

# ----------------------------
# ----------------------------
# Get Quotations for a Project
# ----------------------------
@csrf_exempt
def get_project_quotations(request, project_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Ensure project belongs to logged-in user
        query = "SELECT user_id FROM listed_work WHERE work_id = %s"
        result = fetch_all(query, [project_id])
        if not result or result[0]['user_id'] != user_id:
            return JsonResponse({"error": "Not authorized"}, status=403)

        # Fetch quotations with maker details
        query = """
        SELECT q.quotation_id, q.work_id, q.maker_id, q.description, 
               q.pdf_quotation, q.price, q.estimated_date, q.status, q.created_at,
               u.name AS maker_name, u.email AS maker_email, u.phone AS maker_phone,
               mcd.address AS maker_address
        FROM quotation q
        JOIN users u ON q.maker_id = u.user_id
        LEFT JOIN maker_company_details mcd ON q.maker_id = mcd.maker_id
        WHERE q.work_id = %s
        """
        quotations = fetch_all(query, [project_id])

        # Convert date fields & build URLs
        for q in quotations:
            if q["estimated_date"]:
                q["estimated_date"] = q["estimated_date"].isoformat()
            if q["created_at"]:
                q["created_at"] = q["created_at"].isoformat()
            if q["pdf_quotation"]:
                q["pdf_quotation"] = request.build_absolute_uri(f"/media/{q['pdf_quotation']}")

        return JsonResponse(quotations, safe=False)

    except Exception as e:
        import traceback
        print("Error in get_project_quotations:", traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


# ----------------------------
# Accept a Quotation
# ----------------------------
@csrf_exempt
def accept_quotation(request, quotation_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Get quotation + project details
        query = """
            SELECT q.quotation_id, q.work_id, q.maker_id, q.price, q.estimated_date,
                   lw.user_id, lw.title, lw.description, lw.pdf_report
            FROM quotation q
            JOIN listed_work lw ON q.work_id = lw.work_id
            WHERE q.quotation_id = %s
        """
        result = fetch_all(query, [quotation_id])
        if not result:
            return JsonResponse({"error": "Quotation not found"}, status=404)

        q_data = result[0]
        work_id = q_data["work_id"]
        maker_id = q_data["maker_id"]
        price = q_data["price"]
        completion_date = q_data["estimated_date"]
        project_owner_id = q_data["user_id"]

        # Verify project ownership
        if project_owner_id != user_id:
            return JsonResponse({"error": "Not authorized"}, status=403)

        # Insert into completed_work
        insert_query = """
            INSERT INTO completed_work 
            (user_id, maker_id, quotation_id, title, description, completion_date, price, pdf_report, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        # Convert completion_date to string
        completion_date_str = completion_date.isoformat() if completion_date else None
        params = [
            user_id,
            maker_id,
            q_data["quotation_id"],
            q_data["title"],
            q_data["description"],
            completion_date_str,
            price,
            q_data["pdf_report"]
        ]
        execute_query(insert_query, params)

        # ✅ Update listed_work status to 'Completed' instead of deleting
        update_project_status = """
            UPDATE listed_work
            SET status = 'Completed'
            WHERE work_id = %s
        """
        execute_query(update_project_status, [work_id])

        # Update quotation statuses
        execute_query("UPDATE quotation SET status = 'accepted' WHERE quotation_id = %s", [quotation_id])
        execute_query(
            "UPDATE quotation SET status = 'rejected' WHERE work_id = %s AND quotation_id != %s",
            [work_id, quotation_id]
        )

        return JsonResponse({"message": "Quotation accepted, project marked as completed"}, status=200)

    except Exception as e:
        import traceback
        print("Error in accept_quotation:", traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)
# ----------------------------
# File Upload
# ----------------------------
import cloudinary.uploader # type: ignore
from rest_framework.response import Response
from rest_framework.decorators import api_view

@api_view(["POST"])
def upload_pdf(request):
    file = request.FILES['file']  # Get file from frontend
    result = cloudinary.uploader.upload(
        file,
        resource_type="raw"  # Needed for PDFs
    )
    return Response({"url": result["secure_url"]})

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_project(request, project_id):
    try:
        user_id =request.session.get("user_id")  # current logged-in user ID
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        with connection.cursor() as cursor:
            # ✅ Check if project exists and belongs to this buyer
            cursor.execute("""
                SELECT 1 
                FROM listed_work
                WHERE work_id = %s AND user_id = %s
                LIMIT 1
            """, [project_id, user_id])
            if not cursor.fetchone():
                return JsonResponse({"error": "Project not found"}, status=404)

            # ✅ Check if project has accepted quotations
            cursor.execute("""
                SELECT 1 FROM quotation 
                WHERE work_id = %s AND status = 'accepted'
                LIMIT 1
            """, [project_id])
            if cursor.fetchone():
                return JsonResponse(
                    {"error": "Cannot delete project with accepted quotations"},
                    status=400
                )

            # ✅ Delete quotations first (avoid orphan rows if no ON DELETE CASCADE)
            cursor.execute("""
                DELETE FROM quotation WHERE work_id = %s
            """, [project_id])

            # ✅ Delete the project (hard delete)
            cursor.execute("""
                DELETE FROM listed_work
                WHERE work_id = %s AND user_id = %s
            """, [project_id, user_id])

            if cursor.rowcount == 0:
                return JsonResponse({"error": "Project not found"}, status=404)

        return JsonResponse({"message": "Project deleted permanently"}, status=200)

    except Exception as e:
        import traceback
        print("DELETE ERROR:", traceback.format_exc())  # debug in console
        return JsonResponse({"error": str(e)}, status=500)
