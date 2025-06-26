document.addEventListener('DOMContentLoaded', () => {
    const handleFormSubmit = async (event) => {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        const isAdding = formData.has('add_subcategory');

        const action = isAdding ? 'add' : 'delete';
        const category = formData.get('category');
        const subcategoryName = formData.get('subcategory_name');

        try {
            const response = await fetch('/api/manage-subcategory', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ action, category, subcategory_name: subcategoryName })
            });

            const result = await response.json();

            if (response.ok) {
                if (action === 'add') {
                    add_subcategory_to_dom(category, subcategoryName);
                    form.querySelector('input[name="subcategory_name"]').value = '';
                } else {
                    remove_subcategory_from_dom(category, subcategoryName);
                }
            }
            
            show_flash_message(result.message, result.status);

        } catch (error) {
            console.error('An error occurred:', error);
            show_flash_message('An unexpected error occurred. Please try again.', 'error');
        }
    };

    document.querySelectorAll('.add-subcategory-form, .delete-form').forEach(form => {
        form.addEventListener('submit', handleFormSubmit);
    });
});

function add_subcategory_to_dom(category, subcategoryName) {
    const list = document.getElementById(`subcategory-list-${category}`);
    if (!list) return;

    // Remove the 'No subcategories yet' item if it exists
    const emptyListItem = list.querySelector('.empty-list-item');
    if (emptyListItem) {
        emptyListItem.remove();
    }

    // Create the new list item
    const newItem = document.createElement('li');
    newItem.className = 'list-group-item d-flex justify-content-between align-items-center subcategory-item';
    newItem.id = `subcategory-item-${category}-${subcategoryName}`;
    newItem.textContent = subcategoryName;

    // Create the delete form
    const deleteForm = document.createElement('form');
    deleteForm.method = 'POST';
    deleteForm.className = 'delete-form';
    deleteForm.innerHTML = `
        <input type="hidden" name="category" value="${category}">
        <input type="hidden" name="subcategory_name" value="${subcategoryName}">
        <button type="submit" name="delete_subcategory" value="true" class="btn btn-danger btn-sm delete-btn">
            <i class='bx bx-trash'></i>
        </button>
    `;

    // Add the event listener to the new form
    deleteForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        // Reuse the handler logic or call it directly
        const formData = new FormData(deleteForm);
        const action = 'delete';
        const cat = formData.get('category');
        const subcat = formData.get('subcategory_name');
        const response = await fetch('/api/manage-subcategory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ action, category: cat, subcategory_name: subcat })
        });
        const result = await response.json();
        if(response.ok) remove_subcategory_from_dom(cat, subcat);
        show_flash_message(result.message, result.status);
    });

    newItem.appendChild(deleteForm);
    list.appendChild(newItem);
}

function remove_subcategory_from_dom(category, subcategoryName) {
    const itemToRemove = document.getElementById(`subcategory-item-${category}-${subcategoryName}`);
    if (itemToRemove) {
        itemToRemove.remove();
    }
    
    const list = document.getElementById(`subcategory-list-${category}`);
    if (list && list.children.length === 0) {
        const emptyListItem = document.createElement('li');
        emptyListItem.className = 'list-group-item text-muted empty-list-item';
        emptyListItem.textContent = 'No subcategories yet.';
        list.appendChild(emptyListItem);
    }
}

function show_flash_message(message, category) {
    const container = document.getElementById('flash-container');
    if (!container) return;

    const alert = document.createElement('div');
    alert.className = `alert alert-${category} alert-dismissible fade show`;
    alert.role = 'alert';
    alert.innerHTML = `
        ${message}
        <button type="button" class="close" data-dismiss="alert" aria-label="Close">
            <span aria-hidden="true">&times;</span>
        </button>
    `;
    container.appendChild(alert);

    // Automatically dismiss after 5 seconds
    setTimeout(() => {
        alert.classList.remove('show');
        alert.addEventListener('transitionend', () => alert.remove());
    }, 5000);
}
