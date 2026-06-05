from datetime import date, datetime
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import (
    Booking,
    Oficina,
    ServiceType,
    DURATION_CHOICES,
    BUSINESS_START,
    BUSINESS_END,
    OrdemServicoServiceItem,
    OrdemServicoPartItem,
    OrdemServico,
)


class BookingForm(forms.ModelForm):
    oficina = forms.ModelChoiceField(
        label='Oficina',
        queryset=Oficina.objects.none(),
        empty_label='Selecione a oficina',
        required=False,
        widget=forms.Select(attrs={'id': 'id_oficina'})
    )

    start_time = forms.ChoiceField(
        label='Horário',
        choices=[('', 'Selecione data e duração')],
        widget=forms.Select(attrs={'id': 'id_start_time'})
    )

    duration_minutes = forms.TypedChoiceField(
        label='Tempo estimado do serviço',
        coerce=int,
        choices=DURATION_CHOICES,
        widget=forms.Select(attrs={'id': 'id_duration_minutes'})
    )

    class Meta:
        model = Booking
        fields = [
            'oficina',
            'full_name',
            'phone',
            'vehicle_brand',
            'vehicle_model',
            'vehicle_year',
            'problem_description',
            'service_type',
            'duration_minutes',
            'scheduled_date',
            'start_time',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'placeholder': 'Nome completo'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Telefone'}),
            'vehicle_brand': forms.TextInput(attrs={'placeholder': 'Marca do veículo'}),
            'vehicle_model': forms.TextInput(attrs={'placeholder': 'Modelo do veículo'}),
            'vehicle_year': forms.NumberInput(attrs={'placeholder': 'Ano do veículo', 'min': 1900, 'max': 2100}),
            'problem_description': forms.Textarea(attrs={'placeholder': 'Descreva o problema', 'rows': 4}),
            'service_type': forms.Select(attrs={'id': 'service_type_select'}),
            'scheduled_date': forms.DateInput(attrs={'type': 'date', 'id': 'id_scheduled_date'}),
        }
        labels = {
            'full_name': 'Nome completo',
            'phone': 'Telefone',
            'vehicle_brand': 'Marca do veículo',
            'vehicle_model': 'Modelo do veículo',
            'vehicle_year': 'Ano do veículo',
            'problem_description': 'Descrição do problema',
            'service_type': 'Tipo de serviço',
            'duration_minutes': 'Tempo estimado do serviço',
            'scheduled_date': 'Data desejada',
        }

    def __init__(self, *args, **kwargs):
        self.oficina = kwargs.pop('oficina', None)
        super().__init__(*args, **kwargs)
        if self.oficina is not None:
            self.fields.pop('oficina', None)
        else:
            self.fields['oficina'].queryset = Oficina.objects.order_by('nome')
            self.fields['oficina'].required = True
        self.fields['service_type'].choices = ServiceType.choices
        self.fields['duration_minutes'].choices = DURATION_CHOICES
        self.fields['start_time'].choices = [('', 'Selecione data e duração')]

        scheduled_date = self.data.get('scheduled_date') or self.initial.get('scheduled_date')
        duration = self.data.get('duration_minutes') or self.initial.get('duration_minutes')
        if scheduled_date and duration:
            try:
                scheduled_date_value = datetime.strptime(scheduled_date, '%Y-%m-%d').date()
                duration_value = int(duration)
                oficina_value = self.oficina or self._oficina_from_data()
                self.fields['start_time'].choices = [('', 'Selecione horário')] + Booking.start_time_choices_for_date(
                    scheduled_date_value, duration_value, oficina=oficina_value
                )
            except (ValueError, TypeError):
                pass

    def _oficina_from_data(self):
        oficina_id = self.data.get('oficina') or self.initial.get('oficina')
        if not oficina_id:
            return None
        try:
            return Oficina.objects.get(pk=oficina_id)
        except (Oficina.DoesNotExist, ValueError, TypeError):
            return None

    def clean_scheduled_date(self):
        scheduled_date = self.cleaned_data['scheduled_date']
        if scheduled_date < date.today():
            raise forms.ValidationError(_('A data deve ser hoje ou futura.'))
        return scheduled_date

    def clean(self):
        cleaned = super().clean()
        scheduled_date = cleaned.get('scheduled_date')
        start_time = cleaned.get('start_time')
        duration_minutes = cleaned.get('duration_minutes')
        selected_oficina = self.oficina or cleaned.get('oficina')

        if self.oficina is None and not selected_oficina:
            self.add_error('oficina', _('Selecione a oficina para ver os horários disponíveis.'))

        if start_time and isinstance(start_time, str):
            try:
                cleaned['start_time'] = datetime.strptime(start_time, '%H:%M').time()
            except ValueError:
                self.add_error('start_time', _('Horário inválido. Escolha um horário disponível.'))
                return cleaned

        if scheduled_date and duration_minutes and start_time and selected_oficina:
            if Booking.booked_minutes_for_date(scheduled_date, oficina=selected_oficina) + duration_minutes > 480:
                self.add_error('scheduled_date', _('O limite de 8 horas para este dia foi atingido. Escolha outra data.'))

            if cleaned['start_time'] < BUSINESS_START:
                self.add_error('start_time', _('O horário deve começar a partir de 08:00.'))

            end_minutes = Booking._time_to_minutes(cleaned['start_time']) + duration_minutes
            if end_minutes > Booking._time_to_minutes(BUSINESS_END):
                self.add_error('start_time', _('Este serviço ultrapassa o horário de funcionamento (até 17:00).'))

            if Booking.overlaps(scheduled_date, cleaned['start_time'], duration_minutes, oficina=selected_oficina):
                self.add_error('start_time', _('O horário selecionado já está ocupado. Escolha outro horário.'))

        return cleaned


class OrdemServicoServiceItemForm(forms.ModelForm):
    class Meta:
        model = OrdemServicoServiceItem
        fields = ['description', 'quantity', 'unit_price']
        widgets = {
            'description': forms.TextInput(attrs={
                'placeholder': 'Ex: Troca de óleo',
                'class': 'form-input'
            }),
            'quantity': forms.NumberInput(attrs={
                'min': 1,
                'value': 1,
                'class': 'form-input'
            }),
            'unit_price': forms.NumberInput(attrs={
                'min': 0,
                'step': '0.01',
                'placeholder': 'R$ 0,00',
                'class': 'form-input'
            }),
        }
        labels = {
            'description': 'Serviço',
            'quantity': 'Qtd',
            'unit_price': 'Valor unitário',
        }


class OrdemServicoPartItemForm(forms.ModelForm):
    class Meta:
        model = OrdemServicoPartItem
        fields = ['description', 'quantity', 'unit_price']
        widgets = {
            'description': forms.TextInput(attrs={
                'placeholder': 'Ex: Filtro de óleo',
                'class': 'form-input'
            }),
            'quantity': forms.NumberInput(attrs={
                'min': 1,
                'value': 1,
                'class': 'form-input'
            }),
            'unit_price': forms.NumberInput(attrs={
                'min': 0,
                'step': '0.01',
                'placeholder': 'R$ 0,00',
                'class': 'form-input'
            }),
        }
        labels = {
            'description': 'Peça',
            'quantity': 'Qtd',
            'unit_price': 'Valor unitário',
        }


class OrdemServicoFinancialForm(forms.ModelForm):
    class Meta:
        model = OrdemServico
        fields = [
            'mechanic_name',
            'mileage',
            'payment_method',
            'warranty',
            'observations',
        ]
        widgets = {
            'mechanic_name': forms.TextInput(attrs={
                'placeholder': 'Nome do mecânico',
                'class': 'form-input'
            }),
            'mileage': forms.NumberInput(attrs={
                'min': 0,
                'placeholder': 'Quilometragem',
                'class': 'form-input'
            }),
            'payment_method': forms.Select(attrs={'class': 'form-input'}),
            'warranty': forms.TextInput(attrs={
                'placeholder': '30 dias',
                'class': 'form-input'
            }),
            'observations': forms.Textarea(attrs={
                'placeholder': 'Observações',
                'rows': 3,
                'class': 'form-input'
            }),
        }
        labels = {
            'mechanic_name': 'Mecânico responsável',
            'mileage': 'Quilometragem',
            'payment_method': 'Forma de pagamento',
            'warranty': 'Garantia',
            'observations': 'Observações',
        }


class OrdemServicoStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            ('received', 'Recebido'),
            ('analysis', 'Em análise'),
            ('waiting_approval', 'Aguardando aprovação'),
            ('in_execution', 'Em execução'),
            ('completed', 'Finalizado'),
            ('delivered', 'Entregue'),
            ('canceled', 'Cancelado'),
        ],
        label='Status da OS',
        widget=forms.Select(attrs={'class': 'status-select'})
    )
    note = forms.CharField(
        required=False,
        label='Observações do status',
        widget=forms.Textarea(attrs={'placeholder': 'Descreva a alteração ou observação', 'rows': 3})
    )
