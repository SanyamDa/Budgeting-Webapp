document.addEventListener('DOMContentLoaded', function() {
    const pageBody = document.getElementById('page-body');
    const toggleButton = document.getElementById('sidebar-toggle');

    if (pageBody && toggleButton) {
        // On page load, check if the sidebar was previously collapsed
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            pageBody.classList.add('sidebar-collapsed');
        }

        // Add click listener to the toggle button
        toggleButton.addEventListener('click', function() {
            pageBody.classList.toggle('sidebar-collapsed');
            
            // Save the current state to localStorage
            const isCollapsed = pageBody.classList.contains('sidebar-collapsed');
            localStorage.setItem('sidebarCollapsed', isCollapsed);
        });
    }
});