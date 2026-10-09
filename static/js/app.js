document.addEventListener('DOMContentLoaded', () => {
    const lookupForm = document.getElementById('lookupForm');
    const resultsSection = document.getElementById('resultsSection');
    const jsonTreeView = document.getElementById('jsonTreeView');
    const downloadBtn = document.getElementById('downloadBtn');

    let currentLookupData = null;
    let selectedTemplateId = null;

    if (lookupForm) {
        lookupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const appRef = document.getElementById('appRef').value;
            const templateSelect = document.getElementById('templateSelect');
            selectedTemplateId = templateSelect.value;
            const processCode = templateSelect.options[templateSelect.selectedIndex].getAttribute('data-process');

            if (!selectedTemplateId) {
                alert('Please select a contract template');
                return;
            }

            try {
                const response = await fetch('/api/lookup', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ application_ref: appRef, process_code: processCode })
                });

                const data = await response.json();
                if (response.ok) {
                    currentLookupData = data;
                    renderJsonTree(data, jsonTreeView);
                    resultsSection.style.display = 'block';
                } else {
                    alert('Lookup error: ' + (data.error || 'Failed'));
                }
            } catch (err) {
                alert('Error connecting to backend: ' + err.message);
            }
        });
    }

    if (downloadBtn) 
        {
        downloadBtn.addEventListener('click', async () => {
            if (!currentLookupData || !selectedTemplateId) return;

            try {
                const response = await fetch('/api/download-contract', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        template_id: selectedTemplateId,
                        data: currentLookupData
                    })
                });

                if (response.ok) {
                    // Extract filename from Content-Disposition header if present
                    let filename = 'Contract.docx';
                    const disposition = response.headers.get('Content-Disposition');
                    if (disposition && disposition.includes('filename=')) {
                        filename = disposition
                            .split('filename=')[1]
                            .replace(/["']/g, '')
                            .trim();
                    }

                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                } else {
                    const err = await response.json();
                    alert('Download error: ' + (err.error || 'Failed'));
                }
            } catch (err) {
                alert('Error downloading contract: ' + err.message);
            }
        });
    }

    function renderJsonTree(data, container) {
        container.innerHTML = '';
        container.appendChild(buildTree(data));
    }

    function buildTree(obj) {
        const ul = document.createElement('ul');
        ul.className = 'tree-node';

        for (const key in obj) {
            const li = document.createElement('li');
            const val = obj[key];

            if (typeof val === 'object' && val !== null) {
                const details = document.createElement('details');
                details.open = true;
                const summary = document.createElement('summary');
                summary.innerHTML = `<span class="text-primary">${key}</span>: <small class="text-muted">[${Array.isArray(val) ? 'Array' : 'Object'}]</small>`;
                details.appendChild(summary);
                details.appendChild(buildTree(val));
                li.appendChild(details);
            } else {
                li.innerHTML = `<strong class="text-dark">${key}</strong>: <span class="text-success">${val}</span>`;
            }
            ul.appendChild(li);
        }
        return ul;
    }
});
