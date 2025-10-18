// static/test_harness/test_harness.js

document.addEventListener('DOMContentLoaded', () => {
    // ===================================
    // 1. SELETORES DOS ELEMENTOS
    // ===================================
    const apiTokenInput = document.getElementById('apiToken');
    const paramsContainer = document.getElementById('paramsContainer');
    const submitBtn = document.getElementById('submitBtn');
    const jsonResponse = document.getElementById('jsonResponse');
    const statusDisplay = document.getElementById('statusDisplay');

    const toolsData = JSON.parse(document.getElementById('tools-data').textContent);
    
    // ===================================
    // 2. LÓGICA DO DROPDOWN CUSTOMIZADO
    // ===================================
    function setupCustomSelect(wrapperId) {
        const wrapper = document.getElementById(wrapperId);
        if (!wrapper) return null;

        const button = wrapper.querySelector('.custom-select-button');
        const panel = wrapper.querySelector('.custom-select-panel');
        const searchInput = panel.querySelector('.panel-search');
        const optionsList = panel.querySelector('ul');
        const buttonText = button.querySelector('span');
        
        let value = '';

        const closePanel = () => {
            panel.classList.remove('show');
            button.setAttribute('aria-expanded', 'false');
        };

        button.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.custom-select-panel.show').forEach(otherPanel => {
                if (otherPanel !== panel) {
                    otherPanel.classList.remove('show');
                    const otherButton = otherPanel.previousElementSibling;
                    otherButton.setAttribute('aria-expanded', 'false');
                }
            });

            const isExpanded = panel.classList.toggle('show');
            button.setAttribute('aria-expanded', isExpanded);
            if (isExpanded) {
                searchInput.focus();
                searchInput.select();
            }
        });

        searchInput.addEventListener('input', () => {
            const filter = searchInput.value.toLowerCase();
            optionsList.querySelectorAll('li').forEach(li => {
                const text = li.textContent.toLowerCase();
                li.classList.toggle('hidden', !text.includes(filter));
            });
        });

        optionsList.addEventListener('click', (e) => {
            if (e.target.tagName === 'LI') {
                const selectedValue = e.target.dataset.value;
                const selectedText = e.target.textContent;
                
                if (value !== selectedValue) {
                    value = selectedValue;
                    buttonText.textContent = selectedText;
                    
                    optionsList.querySelectorAll('li').forEach(li => li.classList.remove('selected'));
                    e.target.classList.add('selected');
                    
                    button.dispatchEvent(new CustomEvent('custom:change', { detail: { value: selectedValue } }));
                }
                closePanel();
            }
        });

        return {
            getValue: () => value,
            populate: (items) => {
                optionsList.innerHTML = '';
                if (items && items.length > 0) {
                    items.forEach(item => {
                        const li = document.createElement('li');
                        li.dataset.value = item;
                        li.textContent = item;
                        li.setAttribute('role', 'option');
                        optionsList.appendChild(li);
                    });
                    button.disabled = false;
                } else {
                    button.disabled = true;
                }
            },
            reset: (text) => {
                optionsList.innerHTML = '';
                buttonText.textContent = text;
                value = '';
                button.disabled = true;
                searchInput.value = '';
            }
        };
    }

    const domainSelect = setupCustomSelect('domain-wrapper');
    const analysisSelect = setupCustomSelect('analysis-wrapper');

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.custom-select-wrapper')) {
            document.querySelectorAll('.custom-select-panel.show').forEach(panel => {
                panel.classList.remove('show');
                panel.previousElementSibling.setAttribute('aria-expanded', 'false');
            });
        }
    });

    // ===================================
    // 3. LÓGICA PRINCIPAL DA PÁGINA
    // ===================================
    document.getElementById('domain-btn').addEventListener('custom:change', (e) => {
        const domain = e.detail.value;
        
        analysisSelect.reset('Selecione uma análise...');
        paramsContainer.innerHTML = '<p class="placeholder-text">Selecione uma análise para ver os parâmetros.</p>';
        submitBtn.disabled = true;

        if (toolsData[domain]) {
            analysisSelect.populate(toolsData[domain]);
        }

    });

    document.getElementById('analysis-btn').addEventListener('custom:change', () => {
        paramsContainer.innerHTML = `
            <div class="form-group">
                <label for="paramsInput">Parâmetros da URL</label>
                <input type="text" id="paramsInput" placeholder="Ex: hotel=atibaia&ano=2025&mes=7">
            </div>`;
        submitBtn.disabled = false;
    });

    submitBtn.addEventListener('click', async () => {
        const domain = domainSelect.getValue();
        const analysis = analysisSelect.getValue();
        const token = apiTokenInput.value;

        if (!domain || !analysis || !token) {
            alert('Por favor, selecione o domínio, a análise e forneça um token.');
            return;
        }
        
        // Constrói a query string a partir dos campos
        const paramsInput = document.getElementById('paramsInput');
        const genericParams = paramsInput ? paramsInput.value : '';

        const pageInput = document.getElementById('pageInput');
        const limitInput = document.getElementById('limitInput');
        const page = pageInput ? pageInput.value : '';
        const limit = limitInput ? limitInput.value : '';

        const urlParams = new URLSearchParams(genericParams);
        if (page) {
            urlParams.set('page', page);
        }
        if (limit) {
            urlParams.set('limit', limit);
        }
        
        const url = `/${domain}/analise/${analysis}?${urlParams.toString()}`;
        
        jsonResponse.textContent = 'Carregando...';
        jsonResponse.classList.remove('hljs');
        
        statusDisplay.textContent = 'Enviando...';
        statusDisplay.style.backgroundColor = 'var(--bg-input)';
        statusDisplay.style.color = 'var(--text-primary)';
        
        try {
            const response = await fetch(url, { headers: { 'Authorization': `Bearer ${token}` } });
            const data = await response.json();
            
            if (window.hljs) {
                const jsonString = JSON.stringify(data, null, 2);
                const highlightedCode = hljs.highlight(jsonString, { language: 'json' }).value;
                jsonResponse.innerHTML = highlightedCode;
            } else {
                jsonResponse.textContent = JSON.stringify(data, null, 2);
            }

            statusDisplay.textContent = `Status: ${response.status} ${response.statusText}`;
            statusDisplay.style.backgroundColor = response.ok ? 'var(--green)' : 'var(--red)';
            statusDisplay.style.color = response.ok ? 'var(--bg-dark)' : '#fff';

        } catch (error) {
            jsonResponse.classList.remove('hljs');
            jsonResponse.textContent = `Erro na requisição:\n\n${error.message}`;
            statusDisplay.textContent = 'Erro de Rede';
            statusDisplay.style.backgroundColor = 'var(--red)';
            statusDisplay.style.color = '#fff';
        }
    });
});