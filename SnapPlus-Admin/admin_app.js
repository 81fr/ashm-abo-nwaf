document.addEventListener('DOMContentLoaded', () => {
    // 1. Fetch Real Stats from API
    const fetchStats = async () => {
        try {
            const response = await fetch('http://127.0.0.1:5000/api/admin/stats');
            const data = await response.json();
            
            document.querySelector('.stat-card:nth-child(1) h3').textContent = data.total_users;
            document.querySelector('.stat-card:nth-child(2) h3').textContent = data.active_keys;
            document.querySelector('.stat-card:nth-child(3) h3').textContent = data.protection_level;
            document.querySelector('.stat-card:nth-child(4) h3').textContent = data.current_version;
        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    };

    fetchStats();
    setInterval(fetchStats, 5000); // تحديث تلقائي كل 5 ثواني

    // 2. Search Functionality
    const searchInput = document.querySelector('.search-box input');
    searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const rows = document.querySelectorAll('tbody tr');
        
        rows.forEach(row => {
            const userName = row.querySelector('.user-cell span').textContent.toLowerCase();
            if (userName.includes(term)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });

    // 3. Generate Key via API (Simulated)
    const btnAction = document.querySelector('.btn-action');
    btnAction.addEventListener('click', () => {
        const newKey = 'SNAP-' + Math.random().toString(36).substr(2, 9).toUpperCase();
        alert(`تم توليد مفتاح تفعيل جديد بنجاح وحفظه في النظام: \n${newKey}`);
        
        const tbody = document.querySelector('tbody');
        const newRow = document.createElement('tr');
        newRow.innerHTML = `
            <td>
                <div class="user-cell">
                    <div class="avatar">NEW</div>
                    <span>مستخدم جديد</span>
                </div>
            </td>
            <td>Premium</td>
            <td>${new Date().toISOString().split('T')[0]}</td>
            <td><span class="badge active">نشط</span></td>
            <td>
                <button class="btn-icon"><i class="fas fa-edit"></i></button>
                <button class="btn-icon delete"><i class="fas fa-trash"></i></button>
            </td>
        `;
        tbody.prepend(newRow);
    });
});
