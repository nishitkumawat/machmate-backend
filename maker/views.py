import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import connection

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
            # parse JSON specializations
            result[0]["specializations"] = json.loads(result[0]["specializations"]) if result[0]["specializations"] else []
            return JsonResponse(result[0])
        else:
            return JsonResponse({"exists": False})

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
            print("added")
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
            SELECT lw.work_id as id, lw.title as name, lw.description, 
                   lw.estimated_price as price,
                   lw.estimated_date as estimatedDate, lw.address, lw.state, lw.city, lw.pdf_report as pdfUrl,
                   lw.created_at,
                   (SELECT COUNT(*) FROM quotation q WHERE q.work_id = lw.work_id) as quotation_count
            FROM listed_work lw
            WHERE lw.work_id NOT IN (
                SELECT work_id FROM quotation WHERE maker_id = %s
            )
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
        return JsonResponse(projects, safe=False)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# Create Quotation
# ----------------------------
@csrf_exempt
@require_http_methods(["POST"])
def create_quotation(request, project_id):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        data = json.loads(request.body)

        required_fields = ['amount', 'completionDate', 'description']
        for field in required_fields:
            if field not in data or not data[field]:
                return JsonResponse({"error": f"Missing required field: {field}"}, status=400)

        check_query = "SELECT quotation_id FROM quotation WHERE maker_id = %s AND work_id = %s"
        existing = fetch_all(check_query, [user_id, project_id])
        if existing:
            return JsonResponse({"error": "You have already submitted a quotation for this project"}, status=400)

        project_query = "SELECT work_id FROM listed_work WHERE work_id = %s"
        project = fetch_all(project_query, [project_id])
        if not project:
            return JsonResponse({"error": "Project not found"}, status=404)

        query = """
            INSERT INTO quotation 
            (work_id, maker_id, description, pdf_quotation, price, estimated_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            project_id, user_id, data['description'], data['pdfUrl'],
            data['amount'], data['completionDate'], "pending"
        ]
        execute_query(query, params)
        return JsonResponse({"message": "Quotation submitted successfully"})

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
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
            SELECT q.quotation_id, q.work_id, q.price,
                   q.estimated_date, q.status, q.created_at,
                   lw.title as project_name, lw.description as project_description,
                   lw.estimated_price as project_budget,
                   u.name as buyer_name
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
