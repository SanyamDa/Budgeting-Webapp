"""
Kasikorn Bank (K Bank) API Integration Module via Finverse
Handles OAuth authentication and transaction synchronization
"""

import requests
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
from cryptography.fernet import Fernet
from .models import BankAccount, Transaction, db
import logging

logger = logging.getLogger(__name__)

class KBankAPI:
    def __init__(self):
        self.client_id = os.getenv('FINVERSE_CLIENT_ID')
        self.client_secret = os.getenv('FINVERSE_CLIENT_SECRET')
        # Finverse production host; sandbox host can be set via FINVERSE_USE_SANDBOX=1
        if os.getenv('FINVERSE_USE_SANDBOX') == '1':
            self.api_base_url = 'https://api.sandbox.finverse.net'
        else:
            self.api_base_url = 'https://api.finverse.com'
        # Allow override
        self.api_base_url = os.getenv('FINVERSE_API_URL', self.api_base_url)
        self.redirect_uri = os.getenv('FINVERSE_REDIRECT_URI')
        self.customer_app_id = os.getenv('FINVERSE_CUSTOMER_APP_ID')
        self.institution = os.getenv('FINVERSE_INSTITUTION', 'TH_KBANK')
        
        if not all([self.client_id, self.client_secret, self.redirect_uri, self.customer_app_id]):
            logger.warning("Kasikorn Bank API credentials not fully configured")
    
    def get_client_access_token(self):
        """
        Get client credentials access token for API authentication
        """
        try:
            token_data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            response = requests.post(
                f"{self.api_base_url}/oauth/token",
                data=token_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                token_info = response.json()
                return token_info.get('access_token')
            else:
                logger.error(f"Failed to get client access token: {response.status_code} {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting client access token: {str(e)}")
            return None
    
    def get_authorization_url(self, state=None):
        """
        Create a Finverse link token and return the fully-formed link_url that the
        front-end should redirect the user to. This follows Finverse guidance:
        1. First get client access token via client_credentials flow
        2. POST /link/token with Bearer token → use the returned link_url
        """
        if not all([self.client_id, self.client_secret, self.customer_app_id]):
            logger.error("Missing Finverse credentials for link token")
            return None

        try:
            # Step 1: Get client access token
            access_token = self.get_client_access_token()
            if not access_token:
                logger.error("Failed to obtain client access token")
                return None
            
            # Step 2: Create link token with Bearer authentication
            token_payload = {
                "customer_app_id": self.customer_app_id,
                "institution_id": self.institution,
                "redirect_uri": self.redirect_uri,
                "state": state or "default_state",
                "scope": ["accounts", "transactions"]
            }
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            resp = requests.post(
                f"{self.api_base_url}/link/token",
                json=token_payload,
                headers=headers,
                timeout=30
            )
            
            if resp.status_code == 200:
                link_info = resp.json()
                return link_info.get("link_url")
            else:
                logger.error(f"Failed to create link token: {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Error requesting link token: {e}")
            return None
    
    def exchange_code_for_token(self, authorization_code):
        """
        Exchange authorization code for access token
        """
        try:
            # Prepare token exchange request
            token_data = {
                'grant_type': 'authorization_code',
                'code': authorization_code,
                'redirect_uri': self.redirect_uri,
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }
            
            response = requests.post(
                f"{self.api_base_url}/oauth/token",
                data=token_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                token_info = response.json()
                return {
                    'access_token': token_info['access_token'],
                    'refresh_token': token_info.get('refresh_token'),
                    'expires_in': token_info.get('expires_in', 3600),
                    'token_type': token_info.get('token_type', 'Bearer')
                }
            else:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error exchanging code for token: {str(e)}")
            return None
    
    def refresh_access_token(self, refresh_token):
        """
        Refresh expired access token using refresh token
        """
        try:
            token_data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            
            response = requests.post(
                f"{self.api_base_url}/oauth/token",
                data=token_data,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Token refresh failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return None
    
    def get_accounts(self, access_token):
        """
        Get list of user's bank accounts
        """
        try:
            # Demo mode - return fake account data
            if access_token == 'demo_access_token':
                return {
                    'accounts': [
                        {
                            'account_number': '1234567890',
                            'account_name': 'Demo K Bank Account',
                            'account_type': 'savings',
                            'balance': 50000.00
                        }
                    ]
                }
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(
                f"{self.api_base_url}/accounts",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Get accounts failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting accounts: {str(e)}")
            return None
    
    def get_transactions(self, access_token, account_id, from_date=None, to_date=None, limit=100):
        """
        Get transaction history for specific account
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            # Default to last 30 days if no dates provided
            if not from_date:
                from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            if not to_date:
                to_date = datetime.now().strftime('%Y-%m-%d')
            
            params = {
                'from_date': from_date,
                'to_date': to_date,
                'limit': limit
            }
            
            response = requests.get(
                f"{self.api_base_url}/accounts/{account_id}/transactions",
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Get transactions failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting transactions: {str(e)}")
            return None
    
    def encrypt_token(self, token_data):
        """
        Encrypt API tokens for secure storage
        """
        try:
            # Generate or load encryption key
            key = os.getenv('ENCRYPTION_KEY')
            if not key:
                key = Fernet.generate_key()
                logger.warning("Generated new encryption key - add to .env file")
            else:
                key = key.encode()
            
            fernet = Fernet(key)
            encrypted_token = fernet.encrypt(json.dumps(token_data).encode())
            return base64.b64encode(encrypted_token).decode()
            
        except Exception as e:
            logger.error(f"Error encrypting token: {str(e)}")
            return None
    
    def decrypt_token(self, encrypted_token):
        """
        Decrypt stored API tokens
        """
        try:
            key = os.getenv('ENCRYPTION_KEY').encode()
            fernet = Fernet(key)
            
            encrypted_data = base64.b64decode(encrypted_token.encode())
            decrypted_token = fernet.decrypt(encrypted_data)
            return json.loads(decrypted_token.decode())
            
        except Exception as e:
            logger.error(f"Error decrypting token: {str(e)}")
            return None


def sync_kbank_account(bank_account_id):
    """
    Sync transactions for a Kasikorn Bank account via Finverse
    """
    try:
        bank_account = BankAccount.query.get(bank_account_id)
        if not bank_account or bank_account.bank_name != "Kasikorn Bank":
            return {'success': False, 'error': 'Invalid Kasikorn Bank account'}
        
        api = KBankAPI()
        
        # Decrypt stored tokens
        token_data = api.decrypt_token(bank_account.api_token_encrypted)
        if not token_data:
            return {'success': False, 'error': 'Failed to decrypt API tokens'}
        
        access_token = token_data['access_token']
        
        # Get transactions from API
        transactions_data = api.get_transactions(
            access_token=access_token,
            account_id=bank_account.account_number,
            from_date=bank_account.last_sync_date.strftime('%Y-%m-%d') if bank_account.last_sync_date else None
        )
        
        if not transactions_data:
            return {'success': False, 'error': 'Failed to fetch transactions from Bangkok Bank'}
        
        # Process and save transactions
        new_transactions = 0
        for tx_data in transactions_data.get('transactions', []):
            # Check if transaction already exists
            existing = Transaction.query.filter_by(
                bank_reference=tx_data['transaction_id'],
                bank_account_id=bank_account_id
            ).first()
            
            if not existing:
                # Create new transaction with AI categorization
                transaction = process_kbank_transaction(tx_data, bank_account)
                if transaction:
                    new_transactions += 1
        
        # Update last sync date
        bank_account.last_sync_date = datetime.now()
        db.session.commit()
        
        return {
            'success': True,
            'new_transactions': new_transactions,
            'message': f'Successfully synced {new_transactions} new transactions'
        }
        
    except Exception as e:
        logger.error(f"Error syncing Kasikorn Bank account: {str(e)}")
        return {'success': False, 'error': str(e)}


def process_kbank_transaction(tx_data, bank_account):
    """
    Process a single Kasikorn Bank transaction with AI categorization
    """
    try:
        from .views import parse_transaction_notes_with_ai, process_payee, process_subcategory
        
        # Extract transaction details
        amount = abs(float(tx_data.get('amount', 0)))
        description = tx_data.get('description', 'Bank Transaction')
        transaction_date = datetime.strptime(tx_data.get('date'), '%Y-%m-%d')
        user_notes = tx_data.get('memo', '')  # Bank memo field
        
        # Skip if amount is 0 or positive (incoming transfer)
        if amount <= 0 or tx_data.get('type') != 'debit':
            return None
        
        # AI categorization based on notes or description
        if user_notes:
            ai_result = parse_transaction_notes_with_ai(user_notes, amount)
            payee_name = ai_result.get('payee', 'Unknown Payee')
            main_category = ai_result.get('main_category', 'needs')
            subcategory_name = ai_result.get('subcategory', 'Other')
            sub_exists = ai_result.get('subcategory_exists', False)
        else:
            # Fallback categorization
            payee_name = description[:50] if description else 'Unknown Payee'
            main_category = 'needs'
            subcategory_name = 'Unassigned'
            sub_exists = False
        
        # Get or create payee and category
        payee_id = process_payee(bank_account.plan_id, payee_name)
        category_id = process_subcategory(bank_account.plan_id, main_category, subcategory_name, sub_exists)
        
        # Create transaction
        transaction = Transaction(
            description=f"Kasikorn Bank: {description}",
            amount=amount,
            transaction_date=transaction_date,
            category_id=category_id,
            payee_id=payee_id,
            plan_id=bank_account.plan_id,
            source_type='bank',
            bank_reference=tx_data.get('transaction_id'),
            user_notes=user_notes,
            bank_account_id=bank_account.id
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        return transaction
        
    except Exception as e:
        logger.error(f"Error processing bank transaction: {str(e)}")
        return None
