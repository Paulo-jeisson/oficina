from datetime import date, datetime
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Max
from django.utils.translation import gettext_lazy as _
from .models import (
    BoxBlock,
    Booking,
    Oficina,
    ServiceType,
    SERVICE_TYPE_DEFAULT_DURATION,
    DURATION_CHOICES,
    BUSINESS_START,
    BUSINESS_END,
    OrdemServicoServiceItem,
    OrdemServicoPartItem,
    OrdemServico,
    EstoqueItem,
    EstoqueCategoria,
)
from .whatsapp import normalize_phone


class OficinaSignupForm(UserCreationForm):
    oficina_nome = forms.CharField(
        label='Nome da oficina',
        max_length=120,
        widget=forms.TextInput(attrs={'placeholder': 'Nome da sua oficina'})
    )
    logo = forms.ImageField(label='Logo da oficina', required=False)
    documento = forms.CharField(label='CPF/CNPJ', max_length=20, required=False)
    email = forms.EmailField(label='E-mail', required=True)
    telefone = forms.CharField(label='Telefone/WhatsApp', max_length=25, required=True)
    endereco = forms.CharField(label='Endereco', max_length=180, required=False)
    cidade = forms.CharField(label='Cidade', max_length=80, required=False)
    estado = forms.CharField(label='Estado', max_length=2, required=False)
    business_type = forms.ChoiceField(
        label='Tipo de oficina',
        choices=Oficina.BusinessType.choices,
        initial=Oficina.BusinessType.OTHER,
    )
    mechanic_count = forms.IntegerField(
        label='Quantidade de boxes',
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'min': 1}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.is_staff = True
        if commit:
            user.save()
            oficina = Oficina.objects.create(
                dono=user,
                nome=self.cleaned_data['oficina_nome'],
                logo=self.cleaned_data.get('logo'),
                documento=self.cleaned_data.get('documento', ''),
                email=self.cleaned_data.get('email', ''),
                telefone=self.cleaned_data.get('telefone', ''),
                whatsapp=self.cleaned_data.get('telefone', ''),
                endereco=self.cleaned_data.get('endereco', ''),
                cidade=self.cleaned_data.get('cidade', ''),
                estado=self.cleaned_data.get('estado', '').upper(),
                business_type=self.cleaned_data.get('business_type') or Oficina.BusinessType.OTHER,
                mechanic_count=self.cleaned_data.get('mechanic_count') or 1,
            )
            oficina.ensure_assinatura()
        return user


class OficinaProfileForm(forms.ModelForm):
    class Meta:
        model = Oficina
        fields = [
            'nome',
            'logo',
            'telefone',
            'whatsapp',
            'email',
            'endereco',
            'cidade',
            'estado',
            'cep',
            'descricao',
            'business_type',
            'mechanic_count',
        ]
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 4}),
            'mechanic_count': forms.NumberInput(attrs={'min': 1}),
        }
        labels = {
            'nome': 'Nome da oficina',
            'business_type': 'Tipo de negócio',
            'mechanic_count': 'Quantidade de mecânicos/boxes',
        }

    def clean_telefone(self):
        telefone = self.cleaned_data.get('telefone', '')
        if telefone and not normalize_phone(telefone):
            raise forms.ValidationError('Informe um telefone valido com DDD.')
        return telefone

    def clean_whatsapp(self):
        whatsapp = self.cleaned_data.get('whatsapp', '')
        if whatsapp and not normalize_phone(whatsapp):
            raise forms.ValidationError('Informe um WhatsApp valido com DDD.')
        return whatsapp

    def clean_estado(self):
        return (self.cleaned_data.get('estado') or '').upper()

    def clean_mechanic_count(self):
        mechanic_count = self.cleaned_data['mechanic_count']
        if self.instance and self.instance.pk:
            max_booking_box = Booking.objects.filter(
                oficina=self.instance,
            ).exclude(status=Booking.Status.CANCELED).aggregate(
                max_box=Max('assigned_box')
            )['max_box'] or 0
            max_block_box = BoxBlock.objects.filter(
                oficina=self.instance,
            ).aggregate(
                max_box=Max('box_number')
            )['max_box'] or 0
            minimum_boxes = max(max_booking_box, max_block_box, 1)
            if mechanic_count < minimum_boxes:
                raise forms.ValidationError(
                    f'Nao e possivel reduzir para {mechanic_count}. Existem registros usando o Box {minimum_boxes}.'
                )
        return mechanic_count


class AssinaturaPaymentForm(forms.Form):
    payment_method = forms.ChoiceField(
        label='Forma de pagamento',
        choices=(
            ('PIX', 'Pix'),
            ('CREDIT_CARD', 'Cartao de credito'),
        ),
        widget=forms.Select(attrs={'class': 'form-input'})
    )


BOX_PANEL_DURATION_CHOICES = [
    (30, '30 min'),
    (60, '1h'),
    (90, '1h30'),
    (120, '2h'),
    (180, '3h'),
]


class BookingDurationUpdateForm(forms.Form):
    booking_id = forms.IntegerField(widget=forms.HiddenInput)
    selected_date = forms.DateField(required=False, widget=forms.HiddenInput)
    duration_minutes = forms.TypedChoiceField(
        label='Duração',
        coerce=int,
        choices=BOX_PANEL_DURATION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-input'})
    )


class BoxBlockForm(forms.ModelForm):
    start_datetime = forms.DateTimeField(
        label='Inicio',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    end_datetime = forms.DateTimeField(
        label='Fim',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    class Meta:
        model = BoxBlock
        fields = ['box_number', 'start_datetime', 'end_datetime', 'reason']
        widgets = {
            'box_number': forms.HiddenInput(),
            'reason': forms.TextInput(attrs={'placeholder': 'Motivo do bloqueio'}),
        }
        labels = {
            'start_datetime': 'Inicio',
            'end_datetime': 'Fim',
            'reason': 'Motivo',
        }

    def __init__(self, *args, **kwargs):
        self.oficina = kwargs.pop('oficina', None)
        super().__init__(*args, **kwargs)
        if self.oficina is not None:
            self.instance.oficina = self.oficina

    def clean_box_number(self):
        box_number = self.cleaned_data['box_number']
        if self.oficina and box_number not in Booking.box_indexes_for_oficina(self.oficina):
            raise forms.ValidationError(f'Escolha um Box entre 1 e {self.oficina.mechanic_count}.')
        return box_number

    def clean(self):
        cleaned = super().clean()
        if self.errors or self.oficina is None:
            return cleaned

        block = BoxBlock(
            oficina=self.oficina,
            box_number=cleaned.get('box_number'),
            start_datetime=cleaned.get('start_datetime'),
            end_datetime=cleaned.get('end_datetime'),
            reason=cleaned.get('reason', ''),
        )
        try:
            block.clean()
        except forms.ValidationError as exc:
            if hasattr(exc, 'error_dict'):
                for field, errors in exc.error_dict.items():
                    for error in errors:
                        self.add_error(field, error)
            else:
                self.add_error(None, exc)
        return cleaned

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
        self.assigned_box = None
        super().__init__(*args, **kwargs)
        if self.oficina is not None:
            self.fields.pop('oficina', None)
        else:
            oficinas = Oficina.objects.order_by('nome')
            self.fields['oficina'].queryset = oficinas
            self.fields['oficina'].required = False
            self.fields['oficina'].empty_label = None
            if not self.data and oficinas.exists():
                self.fields['oficina'].initial = oficinas.first()
        self.fields['service_type'].choices = ServiceType.choices
        self.fields['duration_minutes'].choices = DURATION_CHOICES
        self.fields['start_time'].choices = [('', 'Selecione data e duração')]

        scheduled_date = self.data.get('scheduled_date') or self.initial.get('scheduled_date')
        duration = self.data.get('duration_minutes') or self.initial.get('duration_minutes')
        if scheduled_date and duration:
            try:
                scheduled_date_value = self._parse_scheduled_date(scheduled_date)
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
            return Oficina.objects.order_by('nome').first()
        try:
            return Oficina.objects.get(pk=oficina_id)
        except (Oficina.DoesNotExist, ValueError, TypeError):
            return None

    def _parse_scheduled_date(self, value):
        if isinstance(value, date):
            return value
        for date_format in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(value, date_format).date()
            except (ValueError, TypeError):
                continue
        raise ValueError('Invalid date format')

    def clean_scheduled_date(self):
        scheduled_date = self.cleaned_data['scheduled_date']
        if scheduled_date < date.today():
            raise forms.ValidationError(_('A data deve ser hoje ou futura.'))
        return scheduled_date

    def clean(self):
        cleaned = super().clean()
        scheduled_date = cleaned.get('scheduled_date')
        start_time = cleaned.get('start_time')
        service_type = cleaned.get('service_type')
        duration_minutes = cleaned.get('duration_minutes')
        selected_oficina = self.oficina or cleaned.get('oficina')

        if service_type == ServiceType.PERSONAL_ANALYSIS:
            duration_minutes = SERVICE_TYPE_DEFAULT_DURATION[ServiceType.PERSONAL_ANALYSIS]
            cleaned['duration_minutes'] = duration_minutes

        if self.oficina is None and not selected_oficina:
            selected_oficina = Oficina.objects.order_by('nome').first()
            cleaned['oficina'] = selected_oficina
            if selected_oficina is None:
                self.add_error('oficina', _('Nenhuma oficina cadastrada para receber agendamentos.'))

        if start_time and isinstance(start_time, str):
            try:
                cleaned['start_time'] = datetime.strptime(start_time, '%H:%M').time()
            except ValueError:
                self.add_error('start_time', _('Horário inválido. Escolha um horário disponível.'))
                return cleaned

        if scheduled_date and duration_minutes and start_time and selected_oficina:
            if Booking.available_minutes_for_date(scheduled_date, oficina=selected_oficina) < duration_minutes:
                self.add_error('scheduled_date', _('O limite de 10 horas para este dia foi atingido. Escolha outra data.'))

            if cleaned['start_time'] < BUSINESS_START:
                self.add_error('start_time', _('O horário deve começar a partir de 07:00.'))

            if Booking.is_lunch_time(cleaned['start_time']):
                self.add_error('start_time', _('Este horario esta indisponivel para o intervalo de almoco. Escolha outro horario.'))

            if Booking.violates_minimum_lead_time(scheduled_date, cleaned['start_time']):
                self.add_error('start_time', _('Este horario ja passou ou esta muito proximo. Escolha um horario futuro com pelo menos 30 minutos de antecedencia.'))

            end_minutes = Booking.calculate_end_minutes(cleaned['start_time'], duration_minutes)
            if end_minutes is None or end_minutes > Booking._time_to_minutes(BUSINESS_END):
                self.add_error('start_time', _('Este serviço ultrapassa o horário de funcionamento (até 17:00).'))

            available_box = Booking.find_first_available_box(
                scheduled_date,
                cleaned['start_time'],
                duration_minutes,
                oficina=selected_oficina,
            )
            if available_box is None:
                self.add_error('start_time', _('O horário selecionado já está ocupado. Escolha outro horário.'))
            else:
                self.assigned_box = available_box

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
    part_search = forms.CharField(
        required=False, label='Peça',
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Pesquisar por nome, SKU ou código de barras',
            'autocomplete': 'off', 'data-part-search': '1',
        }),
    )
    estoque_item = forms.ModelChoiceField(
        queryset=EstoqueItem.objects.none(), required=True, label='Peça cadastrada',
        widget=forms.HiddenInput(attrs={'data-stock-part': '1'}),
    )

    def __init__(self, *args, oficina=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        if oficina:
            self.fields['estoque_item'].queryset = EstoqueItem.objects.filter(
                oficina=oficina, ativo=True
            ).order_by('nome')

    class Meta:
        model = OrdemServicoPartItem
        fields = ['estoque_item', 'description', 'quantity', 'unit_price']
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

    def clean(self):
        cleaned = super().clean()
        stock_item = cleaned.get('estoque_item')
        if stock_item:
            cleaned['description'] = stock_item.nome
            if not cleaned.get('unit_price'):
                cleaned['unit_price'] = stock_item.preco_venda
        elif not cleaned.get('description'):
            self.add_error('description', 'Informe ou selecione uma peça.')
        return cleaned

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if quantity <= 0:
            raise forms.ValidationError('A quantidade deve ser maior que zero.')
        return quantity


class OrdemServicoPartItemUpdateForm(forms.ModelForm):
    class Meta:
        model = OrdemServicoPartItem
        fields = ['quantity', 'unit_price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-input', 'min': 0, 'step': '0.01'}),
        }

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if quantity <= 0:
            raise forms.ValidationError('A quantidade deve ser maior que zero.')
        return quantity


class EstoqueItemForm(forms.ModelForm):
    class Meta:
        model = EstoqueItem
        fields = [
            'nome', 'codigo', 'codigo_barras', 'categoria', 'marca', 'descricao',
            'estoque_minimo', 'unidade_medida', 'localizacao', 'custo_unitario',
            'preco_venda', 'ativo',
        ]
        widgets = {'descricao': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, oficina=None, **kwargs):
        self.oficina = oficina
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = EstoqueCategoria.objects.filter(oficina=oficina)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        query = EstoqueItem.objects.filter(oficina=self.oficina, codigo__iexact=codigo)
        if self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError('Já existe uma peça com este SKU nesta oficina.')
        return codigo


class EstoqueMovimentoForm(forms.Form):
    tipo = forms.ChoiceField(choices=[
        ('entry', 'Entrada'), ('exit', 'Saída'), ('adjustment', 'Ajuste'),
    ])
    quantidade = forms.IntegerField(min_value=0, label='Quantidade / saldo final')
    custo_unitario = forms.DecimalField(min_value=0, decimal_places=2, required=False)
    observacao = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('tipo') != 'adjustment' and not cleaned.get('quantidade'):
            self.add_error('quantidade', 'A quantidade deve ser maior que zero.')
        if cleaned.get('tipo') == 'exit' and not cleaned.get('observacao', '').strip():
            self.add_error('observacao', 'Informe o motivo da saída.')
        return cleaned


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
