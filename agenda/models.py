from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinValueValidator


class ServiceType(models.TextChoices):
    OIL_CHANGE = 'oil', 'Troca de óleo'
    ALIGNMENT = 'alignment', 'Alinhamento'
    BALANCING = 'balancing', 'Balanceamento'
    BASIC_REVIEW = 'basic_review', 'Revisão básica'
    COMPLETE_REVIEW = 'complete_review', 'Revisão completa'
    ELECTRONIC_DIAGNOSIS = 'electronic_diagnosis', 'Diagnóstico eletrônico'
    CUSTOM = 'custom', 'Serviço personalizado'

SERVICE_TYPE_DEFAULT_DURATION = {
    ServiceType.OIL_CHANGE: 30,
    ServiceType.ALIGNMENT: 60,
    ServiceType.BALANCING: 60,
    ServiceType.BASIC_REVIEW: 120,
    ServiceType.COMPLETE_REVIEW: 240,
    ServiceType.ELECTRONIC_DIAGNOSIS: 60,
    ServiceType.CUSTOM: 30,
}

DURATION_CHOICES = [
    (30, '30 minutos'),
    (60, '1 hora'),
    (90, '1 hora e 30 minutos'),
    (120, '2 horas'),
    (150, '2 horas e 30 minutos'),
    (180, '3 horas'),
    (210, '3 horas e 30 minutos'),
    (240, '4 horas'),
    (270, '4 horas e 30 minutos'),
    (300, '5 horas'),
    (330, '5 horas e 30 minutos'),
    (360, '6 horas'),
    (390, '6 horas e 30 minutos'),
    (420, '7 horas'),
    (450, '7 horas e 30 minutos'),
    (480, '8 horas'),
]

PAYMENT_METHOD_CHOICES = [
    ('cash', 'Dinheiro'),
    ('card', 'Cartão'),
    ('transfer', 'Transferência'),
    ('pix', 'PIX'),
    ('credit', 'Crédito'),
    ('debit', 'Débito'),
    ('other', 'Outro'),
]

TRANSACTION_TYPE_CHOICES = [
    ('receivable', 'A receber'),
    ('payable', 'A pagar'),
    ('cash_in', 'Entrada'),
    ('cash_out', 'Saída'),
]

TRANSACTION_STATUS_CHOICES = [
    ('pending', 'Pendente'),
    ('paid', 'Pago'),
    ('overdue', 'Vencido'),
]

BUSINESS_START = time(7, 0)
BUSINESS_END = time(17, 0)
BUSINESS_MINUTES = 600
SLOT_STEP = 30
LUNCH_BLOCKED_START_TIMES = {time(12, 0), time(12, 30), time(13, 0)}
BOOKING_MIN_LEAD_TIME = timedelta(minutes=30)


class Oficina(models.Model):
    class BusinessType(models.TextChoices):
        CAR = 'car', 'Mecânica de carro'
        MOTORCYCLE = 'motorcycle', 'Mecânica de moto'
        ELECTRICAL = 'electrical', 'Auto elétrica'
        OTHER = 'other', 'Outra'

    nome = models.CharField('Nome da oficina', max_length=120)
    slug = models.SlugField('Slug publico', max_length=140, unique=True, blank=True, null=True)
    logo = models.ImageField('Logo da oficina', upload_to='oficinas/logos/', blank=True, null=True)
    documento = models.CharField('CPF/CNPJ', max_length=20, blank=True)
    email = models.EmailField('E-mail comercial', blank=True)
    telefone = models.CharField('Telefone/WhatsApp', max_length=25, blank=True)
    endereco = models.CharField('Endereco', max_length=180, blank=True)
    cidade = models.CharField('Cidade', max_length=80, blank=True)
    estado = models.CharField('Estado', max_length=2, blank=True)
    dono = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='oficina'
    )
    business_type = models.CharField(
        'Tipo de oficina',
        max_length=20,
        choices=BusinessType.choices,
        default=BusinessType.OTHER,
    )
    mechanic_count = models.PositiveSmallIntegerField(
        'Quantidade de boxes',
        default=1,
        validators=[MinValueValidator(1)],
    )
    created_at = models.DateTimeField('Criada em', auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Oficina'
        verbose_name_plural = 'Oficinas'

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self):
        base_slug = slugify(self.nome) or f'oficina-{self.pk or "nova"}'
        slug = base_slug
        counter = 2
        queryset = Oficina.objects.filter(slug=slug)
        if self.pk:
            queryset = queryset.exclude(pk=self.pk)
        while queryset.exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
            queryset = Oficina.objects.filter(slug=slug)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
        return slug

    def ensure_assinatura(self):
        assinatura, _ = Assinatura.objects.get_or_create(oficina=self)
        return assinatura

    def get_public_booking_url(self):
        return reverse('agenda:public_booking', kwargs={'slug': self.slug})

    def get_box_label(self, box_index):
        return f'Box {box_index or 1}'

    @property
    def assinatura_atual(self):
        return self.ensure_assinatura()


class OficinaOwnedModel(models.Model):
    oficina = models.ForeignKey(
        'agenda.Oficina',
        on_delete=models.CASCADE,
        related_name='%(class)ss',
        verbose_name='Oficina'
    )

    class Meta:
        abstract = True


class Assinatura(models.Model):
    class Status(models.TextChoices):
        TESTE = 'teste', 'Teste'
        ATIVO = 'ativo', 'Ativo'
        VENCIDO = 'vencido', 'Vencido'
        BLOQUEADO = 'bloqueado', 'Bloqueado'
        CANCELADA = 'cancelada', 'Cancelada'

    class FormaPagamento(models.TextChoices):
        PIX = 'pix', 'Pix'
        CARTAO_CREDITO = 'cartao_credito', 'Cartao de credito'

    VALOR_MENSAL_PADRAO = Decimal('99.90')
    DIAS_TESTE_GRATIS = 20
    DIAS_TOLERANCIA_BLOQUEIO = 2

    oficina = models.OneToOneField(
        'agenda.Oficina',
        on_delete=models.CASCADE,
        related_name='assinatura',
        verbose_name='Cliente/empresa',
    )
    status = models.CharField(
        'Status da assinatura',
        max_length=20,
        choices=Status.choices,
        default=Status.TESTE,
    )
    trial_started_at = models.DateField('Inicio do teste gratis', default=timezone.localdate)
    trial_ends_at = models.DateField('Fim do teste gratis', null=True, blank=True)
    due_date = models.DateField('Vencimento da mensalidade', null=True, blank=True)
    last_payment_at = models.DateField('Data do ultimo pagamento', null=True, blank=True)
    payment_method = models.CharField(
        'Forma de pagamento',
        max_length=30,
        choices=FormaPagamento.choices,
        blank=True,
    )
    monthly_amount = models.DecimalField(
        'Valor mensal',
        max_digits=8,
        decimal_places=2,
        default=VALOR_MENSAL_PADRAO,
    )
    asaas_customer_id = models.CharField('ID do cliente no Asaas', max_length=80, blank=True)
    asaas_payment_id = models.CharField('ID da cobranca no Asaas', max_length=80, blank=True)
    asaas_invoice_url = models.URLField('Link de pagamento Asaas', blank=True)
    asaas_pix_payload = models.TextField('Copia e cola Pix', blank=True)
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['oficina__nome']
        verbose_name = 'Assinatura'
        verbose_name_plural = 'Assinaturas'

    def __str__(self):
        return f'{self.oficina.nome} - {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.trial_started_at:
            self.trial_started_at = timezone.localdate()
        if not self.trial_ends_at:
            self.trial_ends_at = self.trial_started_at + timedelta(days=self.DIAS_TESTE_GRATIS)
        if not self.due_date:
            self.due_date = self.trial_ends_at
        if not self.monthly_amount:
            self.monthly_amount = self.VALOR_MENSAL_PADRAO
        super().save(*args, **kwargs)

    @property
    def is_blocked(self):
        return self.status == self.Status.BLOQUEADO

    def should_block(self, reference_date=None):
        reference_date = reference_date or timezone.localdate()
        return (
            self.status in {self.Status.TESTE, self.Status.VENCIDO}
            and self.due_date
            and reference_date > self.due_date + timedelta(days=self.DIAS_TOLERANCIA_BLOQUEIO)
        )

    def refresh_status(self, save=True, reference_date=None):
        reference_date = reference_date or timezone.localdate()
        if self.status == self.Status.BLOQUEADO:
            return self.status
        if self.status == self.Status.CANCELADA:
            if self.due_date and reference_date > self.due_date:
                self.status = self.Status.BLOQUEADO
            else:
                return self.status
        if self.should_block(reference_date=reference_date):
            self.status = self.Status.BLOQUEADO
        elif self.status == self.Status.TESTE and self.trial_ends_at and reference_date > self.trial_ends_at:
            self.status = self.Status.VENCIDO
        elif self.status == self.Status.ATIVO and self.due_date and reference_date > self.due_date:
            self.status = self.Status.VENCIDO
        if save:
            self.save(update_fields=['status', 'updated_at'])
        return self.status

    def mark_paid(self, payment_method=None, paid_at=None):
        paid_at = paid_at or timezone.localdate()
        self.status = self.Status.ATIVO
        self.last_payment_at = paid_at
        self.due_date = paid_at + timedelta(days=30)
        if payment_method:
            self.payment_method = payment_method
        self.save(update_fields=['status', 'last_payment_at', 'due_date', 'payment_method', 'updated_at'])


def format_duration(minutes: int) -> str:
    if minutes == 30:
        return '30 minutos'
    if minutes < 60:
        return f'{minutes} minutos'
    hours = minutes // 60
    remainder = minutes % 60
    if remainder:
        return f'{hours}h {remainder}min'
    return f'{hours}h'


class Booking(OficinaOwnedModel):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Agendado'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        COMPLETED = 'completed', 'Finalizado'
        CANCELED = 'canceled', 'Cancelado'

    full_name = models.CharField('Nome completo', max_length=120)
    phone = models.CharField('Telefone', max_length=25)
    vehicle_brand = models.CharField('Marca do veículo', max_length=80)
    vehicle_model = models.CharField('Modelo do veículo', max_length=80)
    vehicle_year = models.PositiveSmallIntegerField('Ano do veículo')
    problem_description = models.TextField('Problema informado')
    service_type = models.CharField('Tipo de serviço', max_length=20, choices=ServiceType.choices)
    duration_minutes = models.PositiveSmallIntegerField('Tempo estimado (minutos)', choices=DURATION_CHOICES)
    scheduled_date = models.DateField('Data do agendamento')
    start_time = models.TimeField('Horário de início')
    assigned_box = models.PositiveSmallIntegerField(
        'Box alocado',
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField('Status do serviço', max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['scheduled_date', 'start_time', 'full_name']
        verbose_name = 'Agendamento'
        verbose_name_plural = 'Agendamentos'

    def __str__(self):
        return f'{self.full_name} - {self.vehicle_brand} {self.vehicle_model} ({self.scheduled_date} {self.start_time})'

    @property
    def end_time(self) -> time:
        start = datetime.combine(self.scheduled_date, self.start_time)
        end = start + timedelta(minutes=self.duration_minutes)
        return end.time()

    @property
    def duration_label(self) -> str:
        return format_duration(self.duration_minutes)

    @property
    def time_range_label(self) -> str:
        return f'{self.start_time.strftime("%H:%M")} - {self.end_time.strftime("%H:%M")}'

    @property
    def assigned_box_label(self) -> str:
        return f'Box {self.assigned_box or 1}'

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    @property
    def has_os(self) -> bool:
        return hasattr(self, 'ordem_servico')

    @classmethod
    def _time_to_minutes(cls, value: time) -> int:
        return value.hour * 60 + value.minute

    @classmethod
    def _minutes_to_time(cls, minutes: int) -> time:
        return (datetime.combine(date.today(), time.min) + timedelta(minutes=minutes)).time()

    @classmethod
    def _local_datetime(cls, value):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    @classmethod
    def datetime_range_for(cls, scheduled_date, start_time, duration_minutes):
        start = cls._local_datetime(datetime.combine(scheduled_date, start_time))
        end = start + timedelta(minutes=duration_minutes)
        return start, end

    @classmethod
    def _daily_intervals(cls, scheduled_date, oficina=None):
        bookings = cls.objects.filter(scheduled_date=scheduled_date).exclude(status=cls.Status.CANCELED)
        if oficina is not None:
            bookings = bookings.filter(oficina=oficina)
        return sorted(
            (
                cls._time_to_minutes(booking.start_time),
                cls._time_to_minutes(booking.end_time),
            )
            for booking in bookings
        )

    @classmethod
    def box_count_for_oficina(cls, oficina=None):
        if oficina is None:
            return 1
        try:
            return max(int(oficina.mechanic_count or 1), 1)
        except (TypeError, ValueError):
            return 1

    @classmethod
    def box_indexes_for_oficina(cls, oficina=None):
        return range(1, cls.box_count_for_oficina(oficina) + 1)

    @classmethod
    def _daily_intervals_for_box(cls, scheduled_date, oficina, assigned_box, exclude_pk=None):
        bookings = cls.objects.filter(
            scheduled_date=scheduled_date,
            assigned_box=assigned_box,
        ).exclude(status=cls.Status.CANCELED)
        if oficina is not None:
            bookings = bookings.filter(oficina=oficina)
        if exclude_pk:
            bookings = bookings.exclude(pk=exclude_pk)
        return sorted(
            (
                cls._time_to_minutes(booking.start_time),
                cls._time_to_minutes(booking.end_time),
            )
            for booking in bookings
        )

    @classmethod
    def booked_minutes_for_date(cls, scheduled_date, oficina=None):
        bookings = cls.objects.filter(
            scheduled_date=scheduled_date,
        ).exclude(status=cls.Status.CANCELED)
        if oficina is not None:
            bookings = bookings.filter(oficina=oficina)
        return bookings.aggregate(
            total=models.Sum('duration_minutes')
        )['total'] or 0

    @classmethod
    def available_minutes_for_date(cls, scheduled_date, oficina=None):
        total_capacity = BUSINESS_MINUTES * cls.box_count_for_oficina(oficina)
        return max(0, total_capacity - cls.booked_minutes_for_date(scheduled_date, oficina=oficina))

    @classmethod
    def box_has_conflict(cls, scheduled_date, start_time, duration_minutes, oficina=None, assigned_box=1, exclude_pk=None):
        start = cls._time_to_minutes(start_time)
        end = start + duration_minutes
        for current_start, current_end in cls._daily_intervals_for_box(
            scheduled_date,
            oficina,
            assigned_box,
            exclude_pk=exclude_pk,
        ):
            if start < current_end and end > current_start:
                return True
        return False

    @classmethod
    def box_is_blocked(cls, scheduled_date, start_time, duration_minutes, oficina=None, assigned_box=1, exclude_block_pk=None):
        start_dt, end_dt = cls.datetime_range_for(scheduled_date, start_time, duration_minutes)
        blocks = BoxBlock.objects.filter(
            box_number=assigned_box,
            start_datetime__lt=end_dt,
            end_datetime__gt=start_dt,
        )
        if oficina is not None:
            blocks = blocks.filter(oficina=oficina)
        if exclude_block_pk:
            blocks = blocks.exclude(pk=exclude_block_pk)
        return blocks.exists()

    @classmethod
    def available_boxes_for(cls, scheduled_date, start_time, duration_minutes, oficina=None, exclude_pk=None):
        return [
            box_index
            for box_index in cls.box_indexes_for_oficina(oficina)
            if not cls.box_has_conflict(
                scheduled_date,
                start_time,
                duration_minutes,
                oficina=oficina,
                assigned_box=box_index,
                exclude_pk=exclude_pk,
            )
            and not cls.box_is_blocked(
                scheduled_date,
                start_time,
                duration_minutes,
                oficina=oficina,
                assigned_box=box_index,
            )
        ]

    @classmethod
    def find_first_available_box(cls, scheduled_date, start_time, duration_minutes, oficina=None, exclude_pk=None):
        boxes = cls.available_boxes_for(
            scheduled_date,
            start_time,
            duration_minutes,
            oficina=oficina,
            exclude_pk=exclude_pk,
        )
        return boxes[0] if boxes else None

    @classmethod
    def overlaps(cls, scheduled_date, start_time, duration_minutes, oficina=None, assigned_box=None):
        if assigned_box is not None:
            return cls.box_has_conflict(
                scheduled_date,
                start_time,
                duration_minutes,
                oficina=oficina,
                assigned_box=assigned_box,
            )
        return cls.find_first_available_box(scheduled_date, start_time, duration_minutes, oficina=oficina) is None

    @classmethod
    def minimum_start_minutes_for_date(cls, scheduled_date):
        now = timezone.localtime()
        if scheduled_date != now.date():
            return None

        minimum_dt = now + BOOKING_MIN_LEAD_TIME
        if minimum_dt.date() > scheduled_date:
            return cls._time_to_minutes(BUSINESS_END) + SLOT_STEP
        return cls._time_to_minutes(minimum_dt.time())

    @classmethod
    def violates_minimum_lead_time(cls, scheduled_date, start_time):
        minimum_start = cls.minimum_start_minutes_for_date(scheduled_date)
        return minimum_start is not None and cls._time_to_minutes(start_time) < minimum_start

    @classmethod
    def available_start_times_for_date(cls, scheduled_date, duration_minutes, oficina=None):
        if duration_minutes > BUSINESS_MINUTES:
            return []

        if cls.available_minutes_for_date(scheduled_date, oficina=oficina) < duration_minutes:
            return []

        start_min = cls._time_to_minutes(BUSINESS_START)
        end_min = cls._time_to_minutes(BUSINESS_END) - duration_minutes
        if end_min < start_min:
            return []

        result = []
        minimum_start = cls.minimum_start_minutes_for_date(scheduled_date)
        for candidate in range(start_min, end_min + 1, SLOT_STEP):
            if minimum_start is not None and candidate < minimum_start:
                continue
            candidate_time = cls._minutes_to_time(candidate)
            if candidate_time in LUNCH_BLOCKED_START_TIMES:
                continue
            if cls.find_first_available_box(scheduled_date, candidate_time, duration_minutes, oficina=oficina):
                result.append(candidate_time)
        return result

    @classmethod
    def start_time_choices_for_date(cls, scheduled_date, duration_minutes, oficina=None):
        return [
            (time_value.strftime('%H:%M'), time_value.strftime('%H:%M'))
            for time_value in cls.available_start_times_for_date(scheduled_date, duration_minutes, oficina=oficina)
        ]

    @classmethod
    def occupied_intervals_for_date(cls, scheduled_date, oficina=None):
        bookings = cls.objects.filter(scheduled_date=scheduled_date).exclude(status=cls.Status.CANCELED).order_by('start_time')
        if oficina is not None:
            bookings = bookings.filter(oficina=oficina)
        return [
            {
                'label': booking.time_range_label,
                'service': booking.get_service_type_display(),
                'duration': booking.duration_label,
                'customer': booking.full_name,
                'status': booking.status_label,
                'box': booking.assigned_box_label,
            }
            for booking in bookings
        ]

    @classmethod
    def next_available_dates(cls, start_date, required_minutes, limit=5):
        available = []
        candidate = start_date
        while len(available) < limit:
            if cls.available_minutes_for_date(candidate) >= required_minutes:
                available.append(candidate)
            candidate += timedelta(days=1)
        return available

    def get_absolute_url(self):
        return reverse('agenda:booking_success')


class BoxBlock(OficinaOwnedModel):
    box_number = models.PositiveSmallIntegerField(
        'Box',
        validators=[MinValueValidator(1)],
    )
    start_datetime = models.DateTimeField('Inicio do bloqueio')
    end_datetime = models.DateTimeField('Fim do bloqueio')
    reason = models.CharField('Motivo', max_length=180, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['start_datetime', 'box_number']
        verbose_name = 'Bloqueio de Box'
        verbose_name_plural = 'Bloqueios de Box'

    def __str__(self):
        return f'{self.oficina} - {self.box_label} ({self.start_datetime:%d/%m/%Y %H:%M})'

    @property
    def box_label(self):
        return f'Box {self.box_number or 1}'

    @property
    def time_range_label(self):
        return f'{timezone.localtime(self.start_datetime).strftime("%d/%m/%Y %H:%M")} - {timezone.localtime(self.end_datetime).strftime("%d/%m/%Y %H:%M")}'

    @staticmethod
    def ranges_overlap(start_a, end_a, start_b, end_b):
        return start_a < end_b and end_a > start_b

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.start_datetime and timezone.is_naive(self.start_datetime):
            self.start_datetime = timezone.make_aware(self.start_datetime, timezone.get_current_timezone())
        if self.end_datetime and timezone.is_naive(self.end_datetime):
            self.end_datetime = timezone.make_aware(self.end_datetime, timezone.get_current_timezone())

        if self.start_datetime and self.end_datetime and self.end_datetime <= self.start_datetime:
            errors['end_datetime'] = 'A data/hora final deve ser maior que a inicial.'

        oficina = getattr(self, 'oficina', None)
        if self.oficina_id or oficina:
            max_boxes = Booking.box_count_for_oficina(oficina)
            if self.box_number and self.box_number > max_boxes:
                errors['box_number'] = f'Escolha um Box entre 1 e {max_boxes}.'

        if not errors and self.start_datetime and self.end_datetime and self.box_number and oficina:
            conflicting_blocks = BoxBlock.objects.filter(
                oficina=oficina,
                box_number=self.box_number,
                start_datetime__lt=self.end_datetime,
                end_datetime__gt=self.start_datetime,
            )
            if self.pk:
                conflicting_blocks = conflicting_blocks.exclude(pk=self.pk)
            if conflicting_blocks.exists():
                errors['start_datetime'] = 'Ja existe um bloqueio neste Box para o periodo informado.'

            date_start = timezone.localtime(self.start_datetime).date()
            date_end = timezone.localtime(self.end_datetime).date()
            bookings = Booking.objects.filter(
                oficina=oficina,
                assigned_box=self.box_number,
                scheduled_date__range=(date_start, date_end),
            ).exclude(status=Booking.Status.CANCELED)
            for booking in bookings:
                booking_start, booking_end = Booking.datetime_range_for(
                    booking.scheduled_date,
                    booking.start_time,
                    booking.duration_minutes,
                )
                if self.ranges_overlap(self.start_datetime, self.end_datetime, booking_start, booking_end):
                    errors['start_datetime'] = 'Este bloqueio invade um agendamento existente neste Box.'
                    break

        if errors:
            raise ValidationError(errors)


class WhatsAppMessage(OficinaOwnedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        SENT = 'sent', 'Enviado'
        FAILED = 'failed', 'Falhou'

    booking = models.ForeignKey(
        Booking,
        related_name='whatsapp_messages',
        on_delete=models.CASCADE,
        verbose_name='Agendamento',
    )
    destination_phone = models.CharField('Telefone destino', max_length=20)
    message = models.TextField('Mensagem')
    status = models.CharField('Status', max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField('Erro', blank=True)
    sent_at = models.DateTimeField('Enviado em', null=True, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mensagem WhatsApp'
        verbose_name_plural = 'Mensagens WhatsApp'

    def __str__(self):
        return f'{self.destination_phone} - {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.oficina_id and self.booking_id:
            self.oficina = self.booking.oficina
        super().save(*args, **kwargs)


class OrdemServico(OficinaOwnedModel):
    class Status(models.TextChoices):
        RECEBIDO = 'received', 'Recebido'
        ANALYSIS = 'analysis', 'Em análise'
        WAITING_APPROVAL = 'waiting_approval', 'Aguardando aprovação'
        IN_PROGRESS = 'in_execution', 'Em execução'
        COMPLETED = 'completed', 'Finalizado'
        DELIVERED = 'delivered', 'Entregue'
        CANCELED = 'canceled', 'Cancelado'

    booking = models.OneToOneField(
        'agenda.Booking',
        on_delete=models.CASCADE,
        related_name='ordem_servico'
    )
    order_number = models.CharField('Número da OS', max_length=15, unique=True, editable=False)
    client_name = models.CharField('Nome do cliente', max_length=120)
    phone = models.CharField('Telefone', max_length=25)
    vehicle_brand = models.CharField('Marca do veículo', max_length=80)
    vehicle_model = models.CharField('Modelo do veículo', max_length=80)
    vehicle_year = models.PositiveSmallIntegerField('Ano do veículo')
    plate = models.CharField('Placa', max_length=20, blank=True)
    mileage = models.PositiveIntegerField('Quilometragem', null=True, blank=True)
    mechanic_name = models.CharField('Mecânico responsável', max_length=120, blank=True)
    payment_method = models.CharField('Forma de pagamento', max_length=25, choices=PAYMENT_METHOD_CHOICES, blank=True)
    warranty = models.CharField('Garantia do serviço', max_length=120, blank=True, default='30 dias')
    service_value = models.DecimalField('Valor do serviço', max_digits=10, decimal_places=2, default=0)
    parts_value = models.DecimalField('Valor total de peças', max_digits=10, decimal_places=2, default=0)
    total_value = models.DecimalField('Valor total', max_digits=10, decimal_places=2, default=0)
    estimated_profit = models.DecimalField('Lucro estimado', max_digits=10, decimal_places=2, default=0)
    completed_at = models.DateTimeField('Concluído em', null=True, blank=True)
    problem_description = models.TextField('Problema relatado')
    duration_minutes = models.PositiveSmallIntegerField('Tempo estimado (minutos)', choices=DURATION_CHOICES)
    scheduled_date = models.DateField('Data do agendamento')
    observations = models.TextField('Observações da oficina', blank=True)
    status = models.CharField('Status da OS', max_length=20, choices=Status.choices, default=Status.RECEBIDO)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Ordem de Serviço'
        verbose_name_plural = 'Ordens de Serviço'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        note = kwargs.pop('note', '')
        new = self.pk is None
        if not self.order_number:
            self.order_number = self.generate_order_number()
        self.total_value = self.service_value + self.parts_value
        # removed estimated_profit calculation
        if self.status == self.Status.COMPLETED and self.completed_at is None:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)

        if new:
            OrdemServicoStatusHistory.objects.create(
                ordem_servico=self,
                status=self.status,
                user=user,
                note='OS criada' if not note else note,
            )
        elif self._original_status != self.status:
            OrdemServicoStatusHistory.objects.create(
                ordem_servico=self,
                status=self.status,
                user=user,
                note=note,
            )

        self._original_status = self.status

        if self.status == self.Status.COMPLETED:
            self.register_financial_completion(user=user)

    def generate_order_number(self):
        last_os = OrdemServico.objects.order_by('-id').first()
        next_number = 1
        if last_os and last_os.order_number.startswith('OS-'):
            try:
                next_number = int(last_os.order_number.replace('OS-', '')) + 1
            except ValueError:
                next_number = last_os.id + 1
        return f'OS-{next_number:06d}'

    def register_financial_completion(self, user=None):
        if self.status != self.Status.COMPLETED:
            return
        if FinancialTransaction.objects.filter(ordem_servico=self, transaction_type='receivable').exists():
            return

        FinancialTransaction.objects.create(
            oficina=self.oficina,
            ordem_servico=self,
            transaction_type='receivable',
            status='paid',
            amount=self.total_value,
            due_date=self.completed_at.date() if self.completed_at else date.today(),
            paid_at=self.completed_at or timezone.now(),
            payment_method=self.payment_method,
            description=f'Faturamento da OS {self.order_number}',
        )

        CashFlowRecord.objects.create(
            oficina=self.oficina,
            ordem_servico=self,
            entry_type='inflow',
            amount=self.total_value,
            entry_date=self.completed_at.date() if self.completed_at else date.today(),
            description=f'Receita registrada para OS {self.order_number}',
        )

        FinanceAudit.objects.create(
            oficina=self.oficina,
            ordem_servico=self,
            action='OS concluída e faturamento registrado',
            user=user,
            note=f'Valor total R$ {self.total_value:.2f}',
        )

    @property
    def status_label(self):
        return self.get_status_display()

    @property
    def vehicle_description(self):
        return f'{self.vehicle_brand} {self.vehicle_model} ({self.vehicle_year})'

    @property
    def duration_label(self):
        return format_duration(self.duration_minutes)


class OrdemServicoServiceItem(OficinaOwnedModel):
    ordem_servico = models.ForeignKey(
        'agenda.OrdemServico',
        related_name='service_items',
        on_delete=models.CASCADE
    )
    description = models.CharField('Serviço', max_length=180)
    quantity = models.PositiveSmallIntegerField('Quantidade', default=1)
    unit_price = models.DecimalField('Valor unitário', max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Serviço executado'
        verbose_name_plural = 'Serviços executados'

    def __str__(self):
        return f'{self.description} ({self.quantity})'

    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)

    @property
    def total_price(self):
        return self.quantity * self.unit_price


class OrdemServicoPartItem(OficinaOwnedModel):
    ordem_servico = models.ForeignKey(
        'agenda.OrdemServico',
        related_name='part_items',
        on_delete=models.CASCADE
    )
    description = models.CharField('Peça', max_length=180)
    quantity = models.PositiveSmallIntegerField('Quantidade', default=1)
    unit_price = models.DecimalField('Valor unitário', max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Peça utilizada'
        verbose_name_plural = 'Peças utilizadas'

    def __str__(self):
        return f'{self.description} ({self.quantity})'

    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)

    @property
    def total_price(self):
        return self.quantity * self.unit_price


class FinancialTransaction(OficinaOwnedModel):
    ordem_servico = models.ForeignKey(
        'agenda.OrdemServico',
        related_name='transactions',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    transaction_type = models.CharField('Tipo', max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    status = models.CharField('Status', max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='pending')
    amount = models.DecimalField('Valor', max_digits=10, decimal_places=2)
    due_date = models.DateField('Vencimento')
    paid_at = models.DateTimeField('Pago em', null=True, blank=True)
    payment_method = models.CharField('Forma de pagamento', max_length=25, choices=PAYMENT_METHOD_CHOICES, blank=True)
    description = models.TextField('Descrição', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        ordering = ['-due_date', '-created_at']
        verbose_name = 'Movimentação financeira'
        verbose_name_plural = 'Movimentações financeiras'

    def __str__(self):
        return f'{self.get_transaction_type_display()} - R$ {self.amount:.2f}'


    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)


class CashFlowRecord(OficinaOwnedModel):
    ENTRY_CHOICES = [
        ('inflow', 'Entrada'),
        ('outflow', 'Saída'),
    ]
    ordem_servico = models.ForeignKey(
        'agenda.OrdemServico',
        related_name='cash_records',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    entry_date = models.DateField('Data')
    entry_type = models.CharField('Tipo', max_length=20, choices=ENTRY_CHOICES)
    amount = models.DecimalField('Valor', max_digits=10, decimal_places=2)
    description = models.TextField('Descrição', blank=True)

    class Meta:
        ordering = ['-entry_date']
        verbose_name = 'Registro de fluxo de caixa'
        verbose_name_plural = 'Registros de fluxo de caixa'

    def __str__(self):
        return f'{self.get_entry_type_display()} - R$ {self.amount:.2f} em {self.entry_date}'


    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)


class FinanceAudit(OficinaOwnedModel):
    ordem_servico = models.ForeignKey(
        'agenda.OrdemServico',
        related_name='finance_audit',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    action = models.CharField('Ação', max_length=180)
    note = models.TextField('Nota', blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField('Registrado em', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Auditoria financeira'
        verbose_name_plural = 'Auditorias financeiras'

    def __str__(self):
        return f'{self.action} - {self.created_at:%d/%m/%Y %H:%M}'


    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)


class OrdemServicoStatusHistory(OficinaOwnedModel):
    ordem_servico = models.ForeignKey(
        OrdemServico,
        related_name='history',
        on_delete=models.CASCADE
    )
    status = models.CharField('Status', max_length=20, choices=OrdemServico.Status.choices)
    note = models.TextField('Observação', blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField('Registrado em', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Histórico de OS'
        verbose_name_plural = 'Histórico de OS'

    def __str__(self):
        return f'{self.ordem_servico.order_number} - {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.oficina_id and self.ordem_servico_id:
            self.oficina = self.ordem_servico.oficina
        super().save(*args, **kwargs)

    @property
    def author_name(self):
        return self.user.get_full_name() if self.user else 'Sistema'


class EstoqueItem(OficinaOwnedModel):
    nome = models.CharField('Nome do item', max_length=180)
    codigo = models.CharField('Codigo', max_length=60, blank=True)
    quantidade = models.PositiveIntegerField('Quantidade', default=0)
    custo_unitario = models.DecimalField('Custo unitario', max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Item de estoque'
        verbose_name_plural = 'Itens de estoque'
        constraints = [
            models.UniqueConstraint(
                fields=['oficina', 'codigo'],
                condition=models.Q(codigo__gt=''),
                name='unique_codigo_estoque_por_oficina',
            )
        ]

    def __str__(self):
        return self.nome
