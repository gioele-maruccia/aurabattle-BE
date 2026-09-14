"""
Calculate Base Pay Handler - CCNL Turismo

This Lambda function calculates the gross base pay for a company based on:
- Job level (Qa, Qb, 1, 2, 3, 4, 5, 6S, 6, 7)
- Paragraph (I or II) derived from company's fipeArticle
- Article 162 reduction for small businesses (≤15 employees)
- Current date to determine applicable pay from history

Formula:
1. Get base pay for the level and paragraph
2. Update current pay if needed based on effectiveDate in history
3. Add contingency allowance
4. Subtract Article 162 reduction if applicable (small businesses)

Final Pay = Base Pay + Contingency Allowance - Article 162 Reduction (if applicable)
"""

import json
import os
import boto3
from datetime import datetime
from decimal import Decimal

# Initialize AWS services
dynamodb = boto3.resource('dynamodb')
contracts_table = dynamodb.Table(os.environ['CONTRACTS_TABLE_NAME'])
companies_table = dynamodb.Table(os.environ['COMPANIES_TABLE_NAME'])

# Tax constants for net salary estimation
_IRPEF_RATE = 0.23
_IRPEF_DETRAZIONE_LAVORO = 1880.0  # detrazione per redditi da lavoro dipendente
_INPS_RATE = 0.0919


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def calculate_estimated_net(gross_base_pay):
    """
    Stima il netto mensile partendo dal lordo totale (grossBasePay già include superminimo).
    Applica IRPEF (con detrazione lavoro dipendente) e INPS lavoratore.
    Non include addizionali regionali/comunali (non disponibili in questa fase).

    Args:
        gross_base_pay (float): lordo mensile totale (grossBasePay + superminimo già incluso)

    Returns:
        float: netto mensile stimato in EUR
    """
    total_gross = gross_base_pay
    if total_gross <= 0:
        return 0.0
    annual_gross = total_gross * 12
    irpef_annual = max(0.0, annual_gross * _IRPEF_RATE - _IRPEF_DETRAZIONE_LAVORO)
    irpef_monthly = irpef_annual / 12
    inps_monthly = total_gross * _INPS_RATE
    net = total_gross - irpef_monthly - inps_monthly
    return round(net, 2)


def parse_fipe_article(fipe_article):
    """
    Parse fipeArticle to determine paragraph and if Article 162 applies
    
    Examples:
        "Art. 1, I" -> (I, False)
        "Art. 1, II" -> (II, False)
        "Art. 1, I + Art. 162" -> (I, True)
        "Art. 1, II + Art. 162" -> (II, True)
    
    Args:
        fipe_article (str): The fipeArticle string from company data
        
    Returns:
        tuple: (paragraph, has_article_162)
            paragraph: "I" or "II"
            has_article_162: bool indicating if Article 162 reduction applies
    """
    # Check for Article 162
    has_article_162 = "Art. 162" in fipe_article or "Art.162" in fipe_article
    
    # Determine paragraph
    if ", II" in fipe_article or ",II" in fipe_article:
        paragraph = "II"
    else:
        paragraph = "I"  # Default to I
    
    return paragraph, has_article_162


def get_current_base_pay(base_pay_history, reference_date):
    """
    Determine the current applicable base pay based on effective dates
    
    Args:
        base_pay_history (list): List of base pay entries with amount and effectiveDate
        reference_date (datetime): Date to check against (usually today)
        
    Returns:
        Decimal: The applicable base pay amount
    """
    if not base_pay_history:
        return Decimal('0')
    
    # Filter history to only include entries that are effective as of reference_date
    applicable_entries = [
        entry for entry in base_pay_history
        if datetime.fromisoformat(entry['effectiveDate'].replace('Z', '')) <= reference_date
    ]
    
    if not applicable_entries:
        # No entry is effective yet, return the first one
        return Decimal(str(base_pay_history[0]['amount']))
    
    # Sort by effectiveDate descending and get the most recent
    applicable_entries.sort(
        key=lambda x: datetime.fromisoformat(x['effectiveDate'].replace('Z', '')),
        reverse=True
    )
    
    return Decimal(str(applicable_entries[0]['amount']))


def normalize_level(level):
    """
    Normalize job level casing to match Contracts table keys.
    JobRoles table stores 'QA'/'QB', Contracts table expects 'Qa'/'Qb'.
    
    Args:
        level (str): Raw level string (e.g., "QA", "qa", "Qa", "1", "6S")
        
    Returns:
        str: Normalized level string
    """
    LEVEL_MAP = {
        'QA': 'Qa', 'qa': 'Qa',
        'QB': 'Qb', 'qb': 'Qb',
    }
    return LEVEL_MAP.get(level, level)


def get_contract_data(level, ccnl_type='turismo'):
    """
    Retrieve contract data from Contracts table
    
    Args:
        level (str): Job level (e.g., "Qa", "1", "4", etc.)
        ccnl_type (str): Type of CCNL contract (default: "turismo")
        
    Returns:
        dict: Contract data or None if not found
    """
    try:
        level = normalize_level(level)
        contract_id = f"CCNL#{ccnl_type}#{level}"
        response = contracts_table.get_item(
            Key={'contractId': contract_id}
        )
        return response.get('Item')
    except Exception as e:
        print(f"Error fetching contract data for {contract_id}: {str(e)}")
        return None


def get_company_data(user_id):
    """
    Retrieve company data from Companies table
    
    Args:
        user_id (str): User ID (Cognito sub)
        
    Returns:
        dict: Company data or None if not found
    """
    try:
        response = companies_table.get_item(
            Key={'userId': user_id}
        )
        return response.get('Item')
    except Exception as e:
        print(f"Error fetching company data for user {user_id}: {str(e)}")
        return None


def calculate_base_pay(contract, paragraph, has_article_162, reference_date):
    """
    Calculate the gross base pay according to CCNL rules
    
    Args:
        contract (dict): Contract data from DynamoDB
        paragraph (str): "I" or "II"
        has_article_162 (bool): Whether Article 162 reduction applies
        reference_date (datetime): Reference date for calculation
        
    Returns:
        dict: Calculation result with breakdown
    """
    # Get the appropriate base pay structure
    paragraph_key = f"paragraph{paragraph}"
    base_pay_data = contract['basePay'].get(paragraph_key)
    
    if not base_pay_data:
        raise ValueError(f"No base pay data found for paragraph {paragraph}")
    
    # Get current base pay from history
    all_pay_entries = base_pay_data.get('history', [])
    if 'current' in base_pay_data:
        all_pay_entries.append(base_pay_data['current'])
    
    base_pay_amount = get_current_base_pay(all_pay_entries, reference_date)
    
    # Get contingency allowance
    contingency_allowance = Decimal(str(contract.get('contingencyAllowance', 0)))
    
    # Get Article 162 reduction if applicable
    article_162_reduction = Decimal('0')
    if has_article_162:
        article_162_reduction = Decimal(str(contract.get('article162Reduction', 0)))
    
    # Calculate final gross base pay
    gross_base_pay = base_pay_amount + contingency_allowance - article_162_reduction
    
    # Build detailed calculation breakdown
    calculation = {
        'basePay': float(base_pay_amount),
        'contingencyAllowance': float(contingency_allowance),
        'article162Reduction': float(article_162_reduction) if has_article_162 else 0,
        'grossBasePay': float(gross_base_pay),
        'formula': build_formula_string(
            base_pay_amount,
            contingency_allowance,
            article_162_reduction,
            has_article_162
        ),
        'explanation': build_explanation(
            contract['level'],
            contract['levelName'],
            paragraph,
            base_pay_amount,
            contingency_allowance,
            article_162_reduction,
            has_article_162,
            gross_base_pay
        )
    }
    
    return calculation


def build_formula_string(base_pay, contingency, reduction, has_reduction):
    """
    Build the mathematical formula string
    
    Args:
        base_pay (Decimal): Base pay amount
        contingency (Decimal): Contingency allowance
        reduction (Decimal): Article 162 reduction
        has_reduction (bool): Whether reduction applies
        
    Returns:
        str: Formula string
    """
    if has_reduction:
        return f"{float(base_pay):.2f} + {float(contingency):.2f} - {float(reduction):.2f} = {float(base_pay + contingency - reduction):.2f} €"
    else:
        return f"{float(base_pay):.2f} + {float(contingency):.2f} = {float(base_pay + contingency):.2f} €"


def build_explanation(level, level_name, paragraph, base_pay, contingency, 
                      reduction, has_reduction, final_pay):
    """
    Build detailed explanation of the calculation
    
    Returns:
        str: Human-readable explanation
    """
    paragraph_name = "Paragrafo I (aziende standard, incrementi giugno)" if paragraph == "I" else "Paragrafo II (aziende alberghiere, incrementi settembre)"
    
    explanation = f"""Calcolo della retribuzione base lorda per il livello {level} ({level_name}):

1. Paga Base Mensile ({paragraph_name}): {float(base_pay):.2f} €
   - Questo è l'importo base previsto dal CCNL Turismo per il livello {level}
   - Importo aggiornato alla data odierna secondo gli scaglionamenti contrattuali

2. Indennità di Contingenza: +{float(contingency):.2f} €
   - Integrazione retributiva prevista contrattualmente
"""
    
    if has_reduction:
        explanation += f"""
3. Riduzione Art. 162 (Aziende Minori ≤15 dipendenti): -{float(reduction):.2f} €
   - Riduzione applicabile alle aziende con massimo 15 dipendenti
   - Prevista dall'articolo 162 del CCNL Turismo
"""
    
    explanation += f"""
RETRIBUZIONE BASE LORDA MENSILE: {float(final_pay):.2f} €

Questa è la retribuzione minima garantita dal contratto collettivo.
A questa base possono aggiungersi:
- Scatti di anzianità
- Superminimo individuale
- Maggiorazioni per lavoro straordinario, festivo, notturno
- Altre indennità specifiche previste dal CCNL o dall'azienda
"""
    
    return explanation


def lambda_handler(event, context):
    """
    Lambda handler entry point
    
    POST /contracts/calculate-base-pay
    Calculate gross base pay based on company profile and job level.
    
    Request body:
    {
        "level": "4",  // Job level (Qa, Qb, 1, 2, 3, 4, 5, 6S, 6, 7)
        "referenceDate": "2025-11-20"  // Optional: date for calculation (defaults to today)
    }
    
    The company's fipeArticle is automatically retrieved from the authenticated user's profile
    to determine:
    - Paragraph (I or II)
    - Article 162 applicability (small business reduction)
    
    Returns:
        200: Calculation successful with detailed breakdown
        400: Invalid request data
        404: Company or contract not found
        500: Internal server error
    """
    try:
        # Get user ID from Cognito authorizer
        claims = event['requestContext']['authorizer']['claims']
        user_id = claims['sub']
        
        print(f"Calculating base pay for user: {user_id}")
        
        # Parse request body
        body = json.loads(event['body'])
        level = body.get('level')
        superminimo = float(body.get('superminimo') or 0)
        
        if not level:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'Missing required field: level'
                })
            }
        
        # Get reference date (default to today)
        reference_date_str = body.get('referenceDate')
        if reference_date_str:
            try:
                reference_date = datetime.fromisoformat(reference_date_str.replace('Z', ''))
            except ValueError:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'error': 'Bad Request',
                        'message': 'Invalid referenceDate format. Use ISO format: YYYY-MM-DD'
                    })
                }
        else:
            reference_date = datetime.utcnow()
        
        # Get company data
        company = get_company_data(user_id)
        if not company:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not Found',
                    'message': 'No company profile found for this user. Please create a company profile first.'
                })
            }
        
        # MODIFICATO: Verifica se l'azienda è del settore turismo/ristorazione (con FIPE)
        fipe_article = company.get('fipeArticle')
        if not fipe_article or fipe_article == 'None':
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Bad Request',
                    'message': 'This company is not in the tourism/hospitality sector (ATECO 55.xx.xx or 56.xx.xx). Base pay calculation via CCNL Turismo is not applicable.',
                    'suggestion': 'Please enter job details manually when creating a job listing, including role name and gross pay.',
                    'companyInfo': {
                        'businessName': company.get('businessName'),
                        'primaryAtecoCode': company.get('primaryAtecoCode'),
                        'sector': company.get('businessTypeDetails', {}).get('sector', 'non-tourism')
                    }
                })
            }
        
        # Parse fipeArticle to determine paragraph and Article 162 applicability
        fipe_article = company.get('fipeArticle', 'Art. 1, I')
        paragraph, has_article_162 = parse_fipe_article(fipe_article)
        
        print(f"Company: {company.get('businessName')}")
        print(f"FIPE Article: {fipe_article}")
        print(f"Parsed -> Paragraph: {paragraph}, Article 162: {has_article_162}")
        
        # Get contract data
        contract = get_contract_data(level, ccnl_type='turismo')
        if not contract:
            return {
                'statusCode': 404,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Not Found',
                    'message': f'Contract data not found for level: {level}',
                    'suggestion': 'Valid levels are: Qa, Qb, 1, 2, 3, 4, 5, 6S, 6, 7'
                })
            }
        
        # Calculate base pay
        calculation = calculate_base_pay(
            contract=contract,
            paragraph=paragraph,
            has_article_162=has_article_162,
            reference_date=reference_date
        )
        
        print(f"Calculation completed: {calculation['grossBasePay']} € (CCNL)")

        if superminimo > 0:
            ccnl_gross = calculation['grossBasePay']
            gross_with_superminimo = round(ccnl_gross + superminimo, 2)
            base_formula = calculation['formula'].rsplit('=', 1)[0].strip()
            calculation['formula'] = f"{base_formula} + {superminimo:.2f} (superminimo) = {gross_with_superminimo:.2f} \u20ac"
            calculation['grossBasePay'] = gross_with_superminimo
            print(f"Gross with superminimo: {gross_with_superminimo} \u20ac")

        estimated_net = calculate_estimated_net(calculation['grossBasePay'])
        calculation['estimatedNetSalary'] = estimated_net

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Base pay calculated successfully',
                'calculation': calculation,
                'companyInfo': {
                    'businessName': company.get('businessName'),
                    'fipeArticle': fipe_article,
                    'paragraph': paragraph,
                    'isSmallBusiness': has_article_162,
                    'fipeCategory': company.get('fipeCategory')
                },
                'contractInfo': {
                    'level': contract['level'],
                    'levelName': contract['levelName'],
                    'ccnlType': contract['ccnlType'],
                    'description': contract.get('description', '')
                },
                'calculationDate': reference_date.isoformat() + 'Z'
            }, cls=DecimalEncoder)
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'statusCode': 400,
                'error': 'Bad Request',
                'message': 'Invalid JSON in request body'
            })
        }
    except ValueError as e:
        print(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Bad Request',
                'code': 400,
                'message': str(e)
            })
        }
    except Exception as e:
        print(f"Unexpected error calculating base pay: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred while calculating base pay'
            })
        }