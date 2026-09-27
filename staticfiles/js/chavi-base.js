(() => {
    const script = document.currentScript;
    const notificationsUrl = script?.dataset.notificationsUrl;
    const markReadUrl = script?.dataset.markReadUrl;

    window.toggleMobileMenu = () => {
        document.getElementById('mobile-menu')?.classList.toggle('hidden');
    };

    const getCsrfToken = () => {
        const cookie = document.cookie.split('; ').find(item => item.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    };

    const escapeHtml = value => {
        const element = document.createElement('div');
        element.textContent = value ?? '';
        return element.innerHTML;
    };

    const fetchNotifications = () => {
        if (!notificationsUrl) return;
        fetch(notificationsUrl)
            .then(response => response.json())
            .then(data => {
                const badge = document.getElementById('notif-badge');
                const list = document.getElementById('notif-list');
                if (!badge || !list) return;

                if (data.unread_count > 0) {
                    badge.textContent = data.unread_count > 9 ? '9+' : data.unread_count;
                    badge.classList.remove('hidden');
                } else {
                    badge.classList.add('hidden');
                }

                if (data.notifications.length === 0) {
                    list.innerHTML = '<div class="px-4 py-6 text-center text-chavi-charcoal-300 text-sm">No notifications</div>';
                    return;
                }

                const iconMap = {
                    TASK_COMPLETED: 'fa-check-circle text-chavi-primary-600',
                    TASK_FAILED: 'fa-exclamation-circle text-chavi-peach-600',
                    TASK_STALLED: 'fa-pause-circle text-chavi-sun-700',
                    TASK_RESUMED: 'fa-play-circle text-chavi-charcoal-600',
                };
                list.innerHTML = data.notifications.map(notification => {
                    const icon = iconMap[notification.type] || 'fa-bell text-gray-400';
                    const background = notification.is_read ? '' : 'bg-chavi-sun-50';
                    return `<div class="px-4 py-3 border-b border-gray-50 ${background} hover:bg-gray-50">` +
                        '<div class="flex items-start">' +
                        `<i class="fas ${icon} mr-2 mt-0.5"></i>` +
                        '<div class="flex-1 min-w-0">' +
                        `<p class="text-sm font-medium text-gray-900 truncate">${escapeHtml(notification.title)}</p>` +
                        `<p class="text-xs text-gray-500 mt-0.5">${escapeHtml(notification.message)}</p>` +
                        '</div></div></div>';
                }).join('');
            })
            .catch(() => {});
    };

    window.markAllRead = () => {
        if (!markReadUrl) return;
        fetch(markReadUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': getCsrfToken()},
        })
            .then(response => response.json())
            .then(fetchNotifications);
    };

    if (notificationsUrl) {
        fetchNotifications();
        window.setInterval(fetchNotifications, 30000);
    }
})();
