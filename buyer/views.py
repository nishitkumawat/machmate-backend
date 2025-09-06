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

# ----------------------------
# Projects (listed_work)
# ----------------------------
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
                   'Active' AS status
            FROM listed_work
            WHERE user_id=%s
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
    if request.method == "PUT":
        data = json.loads(request.body)

        query = """
            UPDATE listed_work
            SET title=%s, description=%s, estimated_price=%s, estimated_date=%s
            WHERE work_id=%s
        """
        execute_query(query, [
            data["name"], data["description"], data["maxPrice"], data["estimatedDate"], project_id
        ])
        return JsonResponse({"message": "Project updated"}, status=200)

# ----------------------------
# Completed Orders (completed_work)
# ----------------------------
def get_completed_orders(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    query = """
        SELECT cw.completed_id AS id,
               lw.title AS projectName,
               u.name AS makerName,
               cw.price AS amount,
               cw.completion_date AS completionDate
        FROM completed_work cw
        JOIN listed_work lw ON cw.work_id = lw.work_id
        JOIN users u ON cw.maker_id = u.user_id
        WHERE cw.user_id=%s
    """
    orders = fetch_all(query, [user_id])
    return JsonResponse(orders, safe=False)

# ----------------------------
# Quotations
# ----------------------------
@csrf_exempt
def get_project_quotations(request, project_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Check if user owns the project
        query = "SELECT user_id FROM listed_work WHERE work_id = %s"
        result = fetch_all(query, [project_id])
        
        if not result or result[0]['user_id'] != user_id:
            return JsonResponse({"error": "Not authorized"}, status=403)

        # Get quotations for the project
        query = """
            SELECT quotation_id, work_id, maker_id, description, 
                   pdf_quotation, price, estimated_date, created_at
            FROM quotation 
            WHERE work_id = %s
        """
        quotations = fetch_all(query, [project_id])
        
        # Convert date fields to strings for JSON serialization
        for quotation in quotations:
            if quotation['estimated_date']:
                quotation['estimated_date'] = quotation['estimated_date'].isoformat()
            if quotation['created_at']:
                quotation['created_at'] = quotation['created_at'].isoformat()
            
            # Generate full URL for PDF if exists
            if quotation['pdf_quotation']:
                quotation['pdf_quotation'] = request.build_absolute_uri(
                    f"/media/{quotation['pdf_quotation']}"
                )
        
        return JsonResponse(quotations, safe=False)
        
    except Exception as e:
        print("Error in get_project_quotations:", e)
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def accept_quotation(request, quotation_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Get quotation details and verify ownership
        query = """
            SELECT q.work_id, q.maker_id, q.price, q.estimated_date,
                   lw.user_id
            FROM quotation q
            JOIN listed_work lw ON q.work_id = lw.work_id
            WHERE q.quotation_id = %s
        """
        result = fetch_all(query, [quotation_id])
        
        if not result:
            return JsonResponse({"error": "Quotation not found"}, status=404)
        
        quotation_data = result[0]
        work_id = quotation_data['work_id']
        maker_id = quotation_data['maker_id']
        price = quotation_data['price']
        estimated_date = quotation_data['estimated_date']
        project_owner_id = quotation_data['user_id']

        # Verify the user owns the project
        if project_owner_id != user_id:
            return JsonResponse({"error": "Not authorized"}, status=403)

        # Create a new completed order
        query = """
            INSERT INTO completed_work (work_id, user_id, maker_id, price, completion_date)
            VALUES (%s, %s, %s, %s, %s)
        """
        execute_query(query, [work_id, user_id, maker_id, price, estimated_date])
        
        # Update the quotation status to accepted
        query = "UPDATE quotation SET status = 'accepted' WHERE quotation_id = %s"
        execute_query(query, [quotation_id])
        
        # Update all other quotations for this project to rejected
        query = "UPDATE quotation SET status = 'rejected' WHERE work_id = %s AND quotation_id != %s"
        execute_query(query, [work_id, quotation_id])
        
        # Update the project status to completed
        query = "UPDATE listed_work SET status = 'completed' WHERE work_id = %s"
        execute_query(query, [work_id])
        
        return JsonResponse({"message": "Quotation accepted successfully"})
        
    except Exception as e:
        print("Error in accept_quotation:", e)
        return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# File Upload
# ----------------------------
import cloudinary.uploader
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
