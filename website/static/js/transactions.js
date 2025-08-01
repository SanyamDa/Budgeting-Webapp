document.addEventListener('DOMContentLoaded', () => {
  const payeeDropdownTemplate = document.getElementById('payeeDropdownTemplate');
  const table = document.getElementById('transactionsTable');
  let dropdown; // active dropdown element

  // --------- Helper functions ---------
  function closeDropdown() {
    if (dropdown) {
      dropdown.style.display = 'none';
      dropdown.classList.remove('show');
      dropdown = null;
    }
  }

  function buildPayeeList(payees) {
    const listDiv = dropdown.querySelector('.payee-list');
    listDiv.innerHTML = '';
    payees.forEach(p => {
      const item = document.createElement('a');
      item.href = '#';
      item.className = 'dropdown-item';
      item.textContent = p.name;
      item.dataset.payeeId = p.id;
      listDiv.appendChild(item);
    });
  }

  // --------- Dropdown handling ---------
  table.addEventListener('click', async e => {
    const cell = e.target.closest('.payee-cell');
    if (!cell) return;

    // Close any open dropdown first
    closeDropdown();

    // Clone template
    dropdown = payeeDropdownTemplate.cloneNode(true);
    dropdown.id = ''; // remove id
    document.body.appendChild(dropdown);

    // Position near cell
    const rect = cell.getBoundingClientRect();
    dropdown.style.top = `${rect.bottom + window.scrollY}px`;
    dropdown.style.left = `${rect.left + window.scrollX}px`;

    buildPayeeList(window.initialPayees || []);

    dropdown.style.display = 'block';
    dropdown.classList.add('show');

    // Item click
    dropdown.addEventListener('click', async ev => {
      ev.preventDefault();
      const payeeItem = ev.target.closest('.dropdown-item');
      if (!payeeItem) return;

      // Manage Payees
      if (payeeItem.classList.contains('manage-payees')) {
        closeDropdown();
        openManageModal();
        return;
      }

      const payeeId = payeeItem.dataset.payeeId;
      await setTransactionPayee(cell.closest('tr').dataset.transactionId, payeeId);
      cell.textContent = payeeItem.textContent;
      cell.dataset.currentPayee = payeeId;
      closeDropdown();
    }, { once: true });
  });

  document.addEventListener('click', e => {
    if (dropdown && !dropdown.contains(e.target)) closeDropdown();
  });

  // --------- API helpers ---------
  async function api(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    return res.json();
  }

  async function setTransactionPayee(txId, payeeId) {
    await api('POST', `/api/transactions/${txId}/set-payee`, { payee_id: payeeId });
  }

  // --------- Manage Payees Modal ---------
  const manageModal = $('#managePayeesModal');
  const payeesListEl = document.getElementById('payeesList');
  const addBtn = document.getElementById('addPayeeBtn');
  const newNameInput = document.getElementById('newPayeeName');

  function renderPayeeList(payees) {
    payeesListEl.innerHTML = '';
    payees.forEach(p => {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';
      li.textContent = p.name;
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-outline-danger';
      delBtn.innerHTML = '&times;';
      delBtn.addEventListener('click', async () => {
        await api('DELETE', `/api/payees/${p.id}`);
        window.initialPayees = window.initialPayees.filter(x => x.id !== p.id);
        renderPayeeList(window.initialPayees);
      });
      li.appendChild(delBtn);
      payeesListEl.appendChild(li);
    });
  }

  function openManageModal() {
    renderPayeeList(window.initialPayees);
    manageModal.modal('show');
  }

  addBtn.addEventListener('click', async () => {
    const name = newNameInput.value.trim();
    if (!name) return;
    const res = await api('POST', '/api/payees', { name });
    if (res.success) {
      window.initialPayees.push(res.payee);
      newNameInput.value = '';
      renderPayeeList(window.initialPayees);
    }
  });

  // Add event listener for the new Manage Payees button
  const managePayeesBtn = document.getElementById('managePayeesBtn');
  if (managePayeesBtn) {
    managePayeesBtn.addEventListener('click', () => {
      openManageModal();
    });
  }

  // --------- Add Transaction Modal ---------
  const addTransactionModal = $('#addTransactionModal');
  const saveTransactionBtn = document.getElementById('saveTransactionBtn');
  const transactionForm = document.getElementById('addTransactionForm');
  const categorySelect = document.getElementById('transactionCategory');
  const payeeSelect = document.getElementById('transactionPayee');
  const dateInput = document.getElementById('transactionDate');

  // Set default date to today
  const today = new Date().toISOString().split('T')[0];
  dateInput.value = today;

  // Load categories when modal opens
  addTransactionModal.on('show.bs.modal', async () => {
    await loadCategories();
    loadPayeesIntoSelect();
  });

  async function loadCategories() {
    try {
      const res = await api('GET', '/api/categories');
      if (res.success) {
        categorySelect.innerHTML = '<option value="">Select a category...</option>';
        res.categories.forEach(cat => {
          const option = document.createElement('option');
          option.value = cat.id;
          option.textContent = `${cat.main_category.charAt(0).toUpperCase() + cat.main_category.slice(1)} - ${cat.name}`;
          categorySelect.appendChild(option);
        });
      }
    } catch (error) {
      console.error('Failed to load categories:', error);
    }
  }

  function loadPayeesIntoSelect() {
    payeeSelect.innerHTML = '<option value="">Select a payee...</option>';
    window.initialPayees.forEach(payee => {
      const option = document.createElement('option');
      option.value = payee.id;
      option.textContent = payee.name;
      payeeSelect.appendChild(option);
    });
  }

  // Handle transaction form submission
  saveTransactionBtn.addEventListener('click', async () => {
    const description = document.getElementById('transactionDescription').value.trim();
    const amount = parseFloat(document.getElementById('transactionAmount').value);
    const categoryId = parseInt(document.getElementById('transactionCategory').value);
    const payeeId = document.getElementById('transactionPayee').value || null;
    const date = document.getElementById('transactionDate').value;

    if (!description || !amount || !categoryId || !date) {
      alert('Please fill in all required fields.');
      return;
    }

    try {
      saveTransactionBtn.disabled = true;
      saveTransactionBtn.textContent = 'Adding...';

      const res = await api('POST', '/api/add-transaction', {
        description,
        amount,
        category_id: categoryId,
        payee_id: payeeId,
        transaction_date: date
      });

      if (res.success) {
        addTransactionModal.modal('hide');
        transactionForm.reset();
        dateInput.value = today; // Reset to today
        
        // Reload the page to show the new transaction
        window.location.reload();
      } else {
        alert('Failed to add transaction: ' + (res.error || 'Unknown error'));
      }
    } catch (error) {
      console.error('Error adding transaction:', error);
      alert('Failed to add transaction. Please try again.');
    } finally {
      saveTransactionBtn.disabled = false;
      saveTransactionBtn.textContent = 'Add Transaction';
    }
  });
});
