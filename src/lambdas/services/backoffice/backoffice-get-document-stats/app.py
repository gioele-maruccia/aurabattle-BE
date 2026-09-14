import json
import boto3
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import logging
from collections import defaultdict, Counter

# Configurazione logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inizializza il client DynamoDB
dynamodb = boto3.resource('dynamodb')
table_name = os.environ['TABLE_NAME']
table = dynamodb.Table(table_name)
env = os.environ.get('ENV', 'dev')

def decimal_default(obj):
    """Helper function per serializzare Decimal in JSON"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def _cors_response(status_code: int, body: dict) -> dict:
    """Standardized CORS response format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,OPTIONS"
        },
        "body": json.dumps(body, default=decimal_default)
    }

def _parse_doc_item(item: dict) -> dict:
    """Parse document item and extract key information"""
    pk = item.get('pk', '')
    sk = item.get('sk', '')
    
    if not pk.startswith('USER#') or not sk.startswith('DOC#'):
        return None
    
    user_sub = pk.replace('USER#', '')
    sk_parts = sk.replace('DOC#', '').split('#')
    doc_type = sk_parts[0] if len(sk_parts) > 0 else ''
    timestamp = sk_parts[1] if len(sk_parts) > 1 else ''
    
    try:
        timestamp_int = int(timestamp) if timestamp.isdigit() else 0
        # Converti da millisecondi a secondi se necessario
        upload_date = datetime.fromtimestamp(timestamp_int / 1000 if timestamp_int > 1e10 else timestamp_int, tz=timezone.utc) if timestamp_int > 0 else None
    except:
        upload_date = None
    
    return {
        'user_sub': user_sub,
        'doc_type': doc_type,
        'timestamp': timestamp_int,
        'upload_date': upload_date,
        'status': item.get('status', ''),
        'mime': item.get('mime', ''),
        'size': int(item.get('size', 0)) if str(item.get('size', 0)).isdigit() else 0,
        'uploaded_at': item.get('uploadedAt', ''),
        'reviewed_at': item.get('reviewedAt'),
        'reviewed_by': item.get('reviewedBy'),
        'reason': item.get('reason'),
        'rejection_reason': item.get('rejectionReason'),
        'pk': pk,
        'sk': sk
    }

def get_all_documents():
    """Get all documents from DynamoDB for statistics"""
    try:
        logger.info("Starting document scan...")
        
        # Scan semplice senza filtri complessi
        response = table.scan()
        
        documents = []
        total_items = 0
        
        for item in response.get('Items', []):
            total_items += 1
            parsed_doc = _parse_doc_item(item)
            if parsed_doc:
                documents.append(parsed_doc)
        
        logger.info(f"First scan: {total_items} total items, {len(documents)} valid documents")
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            page_total = 0
            page_docs = 0
            
            for item in response.get('Items', []):
                page_total += 1
                total_items += 1
                parsed_doc = _parse_doc_item(item)
                if parsed_doc:
                    documents.append(parsed_doc)
                    page_docs += 1
            
            logger.info(f"Page scan: {page_total} items, {page_docs} valid documents")
            
            # Safety limit
            if total_items > 50000:
                logger.warning("Reached 50k items limit, stopping scan")
                break
        
        logger.info(f"Total scan complete: {total_items} items scanned, {len(documents)} documents found")
        
        if documents:
            logger.info(f"Sample document: {documents[0]}")
            statuses = Counter(doc['status'] for doc in documents)
            logger.info(f"Status distribution: {dict(statuses)}")
        
        return documents
        
    except Exception as e:
        logger.error(f"Error getting documents for stats: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

def calculate_status_statistics(documents):
    """Calculate document status statistics"""
    status_counts = Counter(doc['status'] for doc in documents)
    total_docs = len(documents)
    
    logger.info(f"Status counts: {dict(status_counts)}")
    
    status_stats = {}
    for status, count in status_counts.items():
        percentage = (count / total_docs * 100) if total_docs > 0 else 0
        status_stats[status] = {
            'count': count,
            'percentage': round(percentage, 2)
        }
    
    # Mappa gli stati secondo il sistema reale
    return {
        'total': total_docs,
        'byStatus': status_stats,
        'summary': {
            'pending': (status_counts.get('PENDING', 0) + 
                       status_counts.get('UPLOADED', 0) + 
                       status_counts.get('SCANNING', 0)),
            'awaitingReview': status_counts.get('AWAITING_REVIEW', 0) + status_counts.get('AWAITING_APPROVAL', 0),
            'approved': status_counts.get('APPROVED', 0),
            'rejected': status_counts.get('REJECTED', 0),
            'expired': status_counts.get('EXPIRED', 0)
        }
    }

def calculate_document_type_statistics(documents):
    """Calculate document type statistics"""
    type_counts = Counter(doc['doc_type'] for doc in documents)
    total_docs = len(documents)
    
    logger.info(f"Document type counts: {dict(type_counts)}")
    
    type_stats = {}
    for doc_type, count in type_counts.items():
        percentage = (count / total_docs * 100) if total_docs > 0 else 0
        type_stats[doc_type] = {
            'count': count,
            'percentage': round(percentage, 2)
        }
    
    return {
        'total': total_docs,
        'byType': type_stats
    }

def calculate_temporal_statistics(documents, days_back: int = 30):
    """Calculate temporal statistics for the last N days"""
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=days_back)
    
    # Filtra documenti recenti
    recent_docs = []
    for doc in documents:
        if doc['upload_date'] and doc['upload_date'] >= cutoff_date:
            recent_docs.append(doc)
    
    logger.info(f"Recent documents ({days_back} days): {len(recent_docs)} out of {len(documents)}")
    
    # Group by day
    daily_counts = defaultdict(int)
    for doc in recent_docs:
        if doc['upload_date']:
            day_key = doc['upload_date'].strftime('%Y-%m-%d')
            daily_counts[day_key] += 1
    
    # Calculate trends
    today_count = daily_counts.get(now.strftime('%Y-%m-%d'), 0)
    yesterday_count = daily_counts.get((now - timedelta(days=1)).strftime('%Y-%m-%d'), 0)
    
    # Weekly average
    weekly_total = sum(daily_counts.get((now - timedelta(days=i)).strftime('%Y-%m-%d'), 0) for i in range(7))
    weekly_average = weekly_total / 7
    
    return {
        'periodDays': days_back,
        'totalInPeriod': len(recent_docs),
        'dailyAverage': round(len(recent_docs) / days_back, 2) if days_back > 0 else 0,
        'weeklyAverage': round(weekly_average, 2),
        'today': today_count,
        'yesterday': yesterday_count,
        'trend': 'up' if today_count > yesterday_count else 'down' if today_count < yesterday_count else 'stable',
        'dailyBreakdown': dict(sorted(daily_counts.items(), reverse=True)[:14])
    }

def calculate_user_statistics(documents):
    """Calculate user-related statistics"""
    user_counts = Counter(doc['user_sub'] for doc in documents)
    unique_users = len(user_counts)
    total_docs = len(documents)
    
    # Users with multiple documents
    multi_doc_users = sum(1 for count in user_counts.values() if count > 1)
    
    # Most active users
    top_users = user_counts.most_common(10)
    
    return {
        'uniqueUsers': unique_users,
        'totalDocuments': total_docs,
        'averageDocsPerUser': round(total_docs / unique_users, 2) if unique_users > 0 else 0,
        'usersWithMultipleDocs': multi_doc_users,
        'topUsers': [
            {'userSub': user_sub, 'documentCount': count} 
            for user_sub, count in top_users
        ]
    }

def calculate_reviewer_statistics(documents):
    """Calculate reviewer performance statistics"""
    reviewed_docs = [doc for doc in documents if doc['reviewed_by']]
    
    reviewer_counts = Counter(doc['reviewed_by'] for doc in reviewed_docs)
    
    # Calculate approval rates
    reviewer_stats = {}
    for reviewer in reviewer_counts:
        reviewer_docs = [doc for doc in reviewed_docs if doc['reviewed_by'] == reviewer]
        approved = sum(1 for doc in reviewer_docs if doc['status'] == 'APPROVED')
        rejected = sum(1 for doc in reviewer_docs if doc['status'] == 'REJECTED')
        total = len(reviewer_docs)
        
        approval_rate = (approved / total * 100) if total > 0 else 0
        
        reviewer_stats[reviewer] = {
            'totalReviewed': total,
            'approved': approved,
            'rejected': rejected,
            'approvalRate': round(approval_rate, 2)
        }
    
    return {
        'totalReviewedDocuments': len(reviewed_docs),
        'activeReviewers': len(reviewer_counts),
        'byReviewer': reviewer_stats,
        'topReviewers': [
            {'reviewer': reviewer, 'documentCount': count}
            for reviewer, count in reviewer_counts.most_common(10)
        ]
    }

def verify_admin_access(event: Dict[str, Any]) -> tuple[bool, str, Dict[str, str]]:
    """Verifica che l'utente autenticato sia nel gruppo admins"""
    try:
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        claims = authorizer.get('jwt', {}).get('claims', {}) or authorizer.get('claims', {})
        
        user_sub = claims.get('sub', 'unknown')
        user_email = claims.get('email', 'unknown')
        user_name = claims.get('name', claims.get('cognito:username', 'unknown'))
        
        groups = claims.get('cognito:groups', [])
        if isinstance(groups, str):
            groups = [groups]
        
        logger.info(f"User {user_email} (sub: {user_sub}) attempting access with groups: {groups}")
        
        if 'admins' not in groups:
            logger.warning(f"Access denied for user {user_email} - not in admins group")
            return False, "Access denied: admin privileges required", {}
        
        user_info = {
            'sub': user_sub,
            'email': user_email,
            'name': user_name,
            'groups': groups
        }
        
        logger.info(f"Admin access granted for user {user_email}")
        return True, "", user_info
        
    except Exception as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False, f"Authorization error: {str(e)}", {}

def lambda_handler(event, context):
    """
    Lambda function per ottenere statistiche sui documenti per il backoffice.
    """
    
    logger.info(f"Environment: {env}")
    logger.info(f"Event received: {json.dumps(event, default=str)}")
    
    try:
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return _cors_response(200, {"message": "OK"})
        
        # ========================================
        # VERIFICA ACCESSO ADMIN
        # ========================================
        is_admin, error_msg, admin_info = verify_admin_access(event)
        if not is_admin:
            return _cors_response(403, {
                'success': False,
                'error': 'Forbidden',
                'message': error_msg,
                'environment': env,
                'code': 4343
            })
        
        logger.info(f"Admin {admin_info.get('email')} requesting statistics")
        
        # Parse parametri query
        query_params = event.get('queryStringParameters', {}) or {}
        include_details = query_params.get('details', 'false').lower() == 'true'
        days_back = int(query_params.get('days', 30))
        
        logger.info(f"Parameters: details={include_details}, days={days_back}")
        
        # Validate days_back
        if days_back > 365:
            days_back = 365
        if days_back < 1:
            days_back = 1
        
        # Get all documents
        try:
            documents = get_all_documents()
        except Exception as e:
            return _cors_response(500, {
                'error': 'Internal Server Error',
                "message": f"Failed to retrieve documents: {str(e)}",
                "code": 5097
            })
        
        if not documents:
            return _cors_response(200, {
                "summary": {
                    "totalDocuments": 0,
                    "message": "No documents found in the system"
                },
                "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "code": 3091
            })
        
        logger.info(f"Processing {len(documents)} documents for statistics")
        
        # Calculate basic statistics
        status_stats = calculate_status_statistics(documents)
        doc_type_stats = calculate_document_type_statistics(documents)
        temporal_stats = calculate_temporal_statistics(documents, days_back)
        
        # Build response
        response_data = {
            "success": True,
            "summary": {
                "totalDocuments": len(documents),
                "uniqueUsers": len(set(doc['user_sub'] for doc in documents)),
                "statusBreakdown": status_stats['summary'],
                "documentsToday": temporal_stats['today'],
                "documentsYesterday": temporal_stats['yesterday'],
                "trend": temporal_stats['trend'],
                "averagePerDay": temporal_stats['dailyAverage']
            },
            "statusStatistics": status_stats,
            "temporalStatistics": temporal_stats,
            "documentTypeStatistics": doc_type_stats,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "periodAnalyzed": f"Last {days_back} days",
            "environment": env
        }
        
        # Add detailed statistics if requested
        if include_details:
            user_stats = calculate_user_statistics(documents)
            reviewer_stats = calculate_reviewer_statistics(documents)
            
            response_data.update({
                "userStatistics": user_stats,
                "reviewerStatistics": reviewer_stats
            })
        
        # Add performance insights
        insights = []
        
        # Backlog insights
        awaiting_review = status_stats['summary']['awaitingReview']
        if awaiting_review > 50:
            insights.append({
                "type": "warning",
                "message": f"High backlog: {awaiting_review} documents awaiting review",
                "action": "Consider adding more reviewers or extending review hours"
            })
        elif awaiting_review < 5:
            insights.append({
                "type": "success",
                "message": "Low backlog: Review queue is well managed",
                "action": "Current review capacity is sufficient"
            })
        
        # Trend insights
        if temporal_stats['trend'] == 'up':
            insights.append({
                "type": "info",
                "message": "Document submissions are increasing",
                "action": "Monitor review capacity to handle increased volume"
            })
        
        response_data["insights"] = insights
        
        logger.info(f"Statistics calculated successfully: {len(documents)} documents processed")
        
        return _cors_response(200, {**response_data, 'code': 3092})
        
    except ValueError as e:
        logger.error(f"Invalid parameter: {str(e)}")
        return _cors_response(400, {
            'success': False,
            'error': f'Invalid parameter: {str(e)}',
            'environment': env,
            'code': 4344
        })
        
    except Exception as e:
        logger.error(f"Unexpected error calculating statistics: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return _cors_response(500, {
            'success': False,
            'error': 'Internal Server Error',
            'message': 'Internal server error',
            'environment': env,
            'errorType': type(e).__name__ if env == 'dev' else None,
            'code': 5098
        })