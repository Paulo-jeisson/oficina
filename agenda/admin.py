from django.contrib import admin
from .models import (
    BoxBlock,
    Booking,
    Assinatura,
    Oficina,
    OrdemServico,
    OrdemServicoStatusHistory,
    OrdemServicoServiceItem,
    OrdemServicoPartItem,
    FinancialTransaction,
    CashFlowRecord,
    FinanceAudit,
    EstoqueItem,
    WhatsAppMessage,
)


class AssinaturaInline(admin.StackedInline):
    model = Assinatura
    extra = 0
    fields = (
        'status',
        'trial_started_at',
        'trial_ends_at',
        'due_date',
        'last_payment_at',
        'payment_method',
        'monthly_amount',
        'asaas_customer_id',
        'asaas_payment_id',
        'asaas_invoice_url',
    )


@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'business_type', 'mechanic_count', 'email', 'telefone', 'dono', 'created_at')
    list_filter = ('business_type', 'mechanic_count')
    search_fields = ('nome', 'email', 'telefone', 'documento', 'dono__username', 'dono__email')
    readonly_fields = ('created_at',)
    inlines = [AssinaturaInline]


@admin.register(Assinatura)
class AssinaturaAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'status', 'due_date', 'last_payment_at', 'payment_method', 'monthly_amount', 'asaas_payment_id')
    list_filter = ('status', 'payment_method', 'due_date')
    search_fields = ('oficina__nome', 'oficina__dono__username', 'oficina__dono__email')
    actions = ['marcar_como_pago']

    @admin.action(description='Marcar cliente como ativo/pago')
    def marcar_como_pago(self, request, queryset):
        for assinatura in queryset:
            assinatura.mark_paid(payment_method=assinatura.payment_method or Assinatura.FormaPagamento.PIX)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'oficina',
        'full_name',
        'phone',
        'vehicle_brand',
        'vehicle_model',
        'vehicle_year',
        'scheduled_date',
        'start_time',
        'box_label',
        'duration_minutes',
        'status',
    )
    list_filter = ('oficina', 'status', 'scheduled_date', 'service_type', 'assigned_box')
    search_fields = ('full_name', 'phone', 'vehicle_brand', 'vehicle_model')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Box')
    def box_label(self, obj):
        return obj.assigned_box_label


@admin.register(BoxBlock)
class BoxBlockAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'box_number', 'start_datetime', 'end_datetime', 'reason', 'created_at')
    list_filter = ('oficina', 'box_number', 'start_datetime', 'end_datetime')
    search_fields = ('oficina__nome', 'reason')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'booking', 'destination_phone', 'status', 'sent_at', 'created_at')
    list_filter = ('oficina', 'status', 'created_at', 'sent_at')
    search_fields = ('destination_phone', 'message', 'error', 'booking__full_name')
    readonly_fields = ('oficina', 'booking', 'destination_phone', 'message', 'status', 'error', 'sent_at', 'created_at', 'updated_at')


class OrdemServicoStatusInline(admin.TabularInline):
    model = OrdemServicoStatusHistory
    extra = 0
    readonly_fields = ('status', 'note', 'user', 'created_at')
    can_delete = False


class OrdemServicoServiceItemInline(admin.TabularInline):
    model = OrdemServicoServiceItem
    extra = 0


class OrdemServicoPartItemInline(admin.TabularInline):
    model = OrdemServicoPartItem
    extra = 0


@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = (
        'oficina',
        'order_number',
        'client_name',
        'vehicle_brand',
        'vehicle_model',
        'scheduled_date',
        'duration_minutes',
        'status',
    )
    list_filter = ('oficina', 'status', 'scheduled_date')
    search_fields = ('order_number', 'client_name', 'vehicle_brand', 'vehicle_model')
    readonly_fields = ('order_number', 'created_at', 'updated_at')
    inlines = [OrdemServicoStatusInline, OrdemServicoServiceItemInline, OrdemServicoPartItemInline]


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'ordem_servico', 'transaction_type', 'status', 'amount', 'due_date', 'payment_method')
    list_filter = ('oficina', 'transaction_type', 'status', 'payment_method')
    search_fields = ('ordem_servico__order_number', 'description')


@admin.register(CashFlowRecord)
class CashFlowRecordAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'entry_date', 'entry_type', 'amount', 'ordem_servico')
    list_filter = ('oficina', 'entry_type')
    search_fields = ('description', 'ordem_servico__order_number')


@admin.register(FinanceAudit)
class FinanceAuditAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'action', 'ordem_servico', 'user', 'created_at')
    list_filter = ('oficina', 'user')
    search_fields = ('action', 'note')


@admin.register(EstoqueItem)
class EstoqueItemAdmin(admin.ModelAdmin):
    list_display = ('oficina', 'nome', 'codigo', 'quantidade', 'custo_unitario')
    list_filter = ('oficina',)
    search_fields = ('nome', 'codigo')
