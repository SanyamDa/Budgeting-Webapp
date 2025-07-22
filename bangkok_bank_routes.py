# Bangkok Bank OAuth Routes - to be appended to views.py

# Bangkok Bank OAuth Routes
@views.route('/auth/bangkok-bank')
@login_required
def bangkok_bank_auth():
    """Initiate Bangkok Bank OAuth authentication"""
    try:
        api = BangkokBankAPI()
        
        # Generate state parameter for security
        state = f"user_{current_user.id}_plan_{current_user.active_plan.id}"
        
        # Get authorization URL
        auth_url = api.get_authorization_url(state=state)
        
        if not auth_url:
            flash('Bangkok Bank API not configured. Please check API credentials.', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        # Redirect user to Bangkok Bank for authentication
        return redirect(auth_url)
        
    except Exception as e:
        flash(f'Error initiating Bangkok Bank authentication: {str(e)}', 'error')
        return redirect(url_for('views.bank_accounts'))


@views.route('/auth/bangkok-bank/callback')
@login_required
def bangkok_bank_callback():
    """Handle Bangkok Bank OAuth callback"""
    try:
        # Get authorization code from callback
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        
        if error:
            flash(f'Bangkok Bank authentication failed: {error}', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        if not code:
            flash('No authorization code received from Bangkok Bank', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        # Verify state parameter
        expected_state = f"user_{current_user.id}_plan_{current_user.active_plan.id}"
        if state != expected_state:
            flash('Invalid state parameter. Authentication failed.', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        # Exchange code for access token
        api = BangkokBankAPI()
        token_data = api.exchange_code_for_token(code)
        
        if not token_data:
            flash('Failed to obtain access token from Bangkok Bank', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        # Get user's bank accounts from API
        accounts_data = api.get_accounts(token_data['access_token'])
        
        if not accounts_data:
            flash('Failed to retrieve account information from Bangkok Bank', 'error')
            return redirect(url_for('views.bank_accounts'))
        
        # Process and save bank accounts
        new_accounts = 0
        for account_data in accounts_data.get('accounts', []):
            # Check if account already exists
            existing = BankAccount.query.filter_by(
                account_number=account_data['account_number'],
                plan_id=current_user.active_plan.id
            ).first()
            
            if not existing:
                # Encrypt and store API tokens
                encrypted_token = api.encrypt_token(token_data)
                
                # Create new bank account record
                bank_account = BankAccount(
                    bank_name="Bangkok Bank",
                    account_number=account_data['account_number'],
                    account_holder_name=account_data.get('account_name', 'Account Holder'),
                    nickname=f"BBL {account_data['account_number'][-4:]}",
                    api_token_encrypted=encrypted_token,
                    is_active=True,
                    plan_id=current_user.active_plan.id
                )
                
                db.session.add(bank_account)
                new_accounts += 1
        
        db.session.commit()
        
        if new_accounts > 0:
            flash(f'Successfully linked {new_accounts} Bangkok Bank account(s)!', 'success')
        else:
            flash('Bangkok Bank accounts already linked', 'info')
        
        return redirect(url_for('views.bank_accounts'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing Bangkok Bank authentication: {str(e)}', 'error')
        return redirect(url_for('views.bank_accounts'))


@views.route('/api/bank_accounts/<int:account_id>', methods=['DELETE'])
@login_required
def remove_bank_account(account_id):
    """Remove/deactivate a bank account"""
    try:
        account = BankAccount.query.filter_by(
            id=account_id,
            plan_id=current_user.active_plan.id
        ).first()
        
        if not account:
            return jsonify({'success': False, 'message': 'Bank account not found'})
        
        # Deactivate instead of deleting to preserve transaction history
        account.is_active = False
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Bank account removed successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error removing account: {str(e)}'})
