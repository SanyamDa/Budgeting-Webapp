(function() {
    const getStoredTheme = () => localStorage.getItem('theme');
    const getInitialTheme = () => {
        const initialTheme = document.documentElement.getAttribute('data-initial-theme');
        if (initialTheme) {
            return initialTheme;
        }
        return getStoredTheme() || 'system';
    };
    const applyTheme = (theme) => {
        if (theme === 'system') {
            const now = new Date();
            const hour = now.getHours();
            const minute = now.getMinutes();

            // Set dark mode from 6:30 PM (18:30) to 6:30 AM (06:30)
            const isDarkModeTime = (hour > 18 || (hour === 18 && minute >= 30)) || (hour < 6 || (hour === 6 && minute < 30));
            
            document.documentElement.setAttribute('data-theme', isDarkModeTime ? 'dark' : 'light');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
    };

    let currentTheme = getInitialTheme();
    applyTheme(currentTheme);
})()
