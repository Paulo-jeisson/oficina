document.addEventListener('DOMContentLoaded', function () {
    const serviceTypeSelect = document.getElementById('service_type_select');
    const oficinaSelect = document.getElementById('id_oficina');
    const dateInput = document.getElementById('id_scheduled_date');
    const durationSelect = document.getElementById('id_duration_minutes');
    const startTimeSelect = document.getElementById('id_start_time');
    const slotMessage = document.getElementById('slotMessage');
    const bookingShell = document.querySelector('[data-booking-oficina-slug]');

    const defaultDuration = {
        oil: '30',
        personal_analysis: '60',
        basic_review: '120',
        complete_review: '240',
        electronic_diagnosis: '60',
        custom: '30',
    };

    function updateStartTimes() {
        if (!dateInput || !durationSelect || !startTimeSelect || !slotMessage) {
            return;
        }

        startTimeSelect.disabled = false;
        const selectedDate = dateInput.value;
        const selectedDuration = durationSelect.value;

        if (!selectedDate || !selectedDuration) {
            startTimeSelect.innerHTML = '<option value="">Selecione data e duração</option>';
            slotMessage.textContent = 'Selecione data e duração para ver os horários disponíveis.';
            return;
        }

        const params = new URLSearchParams({
            date: selectedDate,
            duration: selectedDuration,
        });
        if (oficinaSelect && oficinaSelect.value) {
            params.set('oficina', oficinaSelect.value);
        }
        if (bookingShell && bookingShell.dataset.bookingOficinaSlug) {
            params.set('oficina_slug', bookingShell.dataset.bookingOficinaSlug);
        }

        fetch(`/agendar/available-slots/?${params.toString()}`)
            .then((response) => response.json())
            .then((data) => {
                startTimeSelect.innerHTML = '';
                if (data.slots.length === 0) {
                    startTimeSelect.disabled = true;
                    slotMessage.textContent = data.message || 'Nenhum horário disponível para a combinação selecionada.';
                    return;
                }

                startTimeSelect.innerHTML = '<option value="">Selecione um horário</option>';
                data.slots.forEach((slot) => {
                    const option = document.createElement('option');
                    option.value = slot;
                    option.textContent = slot;
                    startTimeSelect.appendChild(option);
                });
                slotMessage.textContent = data.message || `${data.slots.length} horário(s) disponível(is).`;
            })
            .catch(() => {
                startTimeSelect.innerHTML = '<option value="">Erro ao carregar horários</option>';
                slotMessage.textContent = 'Não foi possível carregar os horários. Tente novamente.';
            });
    }

    function setDefaultDuration() {
        if (!serviceTypeSelect || !durationSelect) {
            return;
        }
        const defaultValue = defaultDuration[serviceTypeSelect.value];
        if (defaultValue && durationSelect.value !== defaultValue) {
            durationSelect.value = defaultValue;
        }
    }

    if (serviceTypeSelect) {
        serviceTypeSelect.addEventListener('change', function () {
            setDefaultDuration();
            updateStartTimes();
        });
    }

    if (oficinaSelect) {
        oficinaSelect.addEventListener('change', updateStartTimes);
    }

    if (dateInput) {
        dateInput.addEventListener('change', updateStartTimes);
    }

    if (durationSelect) {
        durationSelect.addEventListener('change', updateStartTimes);
    }

    setDefaultDuration();
    updateStartTimes();

    document.querySelectorAll('[data-copy-target]').forEach((button) => {
        button.addEventListener('click', function () {
            const target = document.querySelector(button.dataset.copyTarget);
            if (!target) {
                return;
            }
            const value = target.value || target.textContent;
            navigator.clipboard.writeText(value).then(() => {
                const originalText = button.textContent;
                button.textContent = 'Link copiado';
                window.setTimeout(() => {
                    button.textContent = originalText;
                }, 1800);
            });
        });
    });
});
