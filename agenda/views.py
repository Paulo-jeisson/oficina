from datetime import date, datetime, timedelta
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods
from django.views.generic import FormView, TemplateView, View
from django.urls import reverse_lazy
from django.db.models import Q, Sum, Count, Avg, F, Case, When, Value, DecimalField
from .forms import BookingForm, OrdemServicoStatusForm, OrdemServicoServiceItemForm, OrdemServicoPartItemForm, OrdemServicoFinancialForm
from .models import (
    Booking,
    ServiceType,
    OrdemServico,
    OrdemServicoStatusHistory,
    OrdemServicoServiceItem,
    OrdemServicoPartItem,
    FinancialTransaction,
    CashFlowRecord,
    FinanceAudit,
    Oficina,
)
from .utils import enviar_whatsapp
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import threading


@require_http_methods(['GET', 'POST'])
def logout_view(request):
    logout(request)
    return redirect('agenda:login')


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy('agenda:login')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            self._ensure_user_oficina()
        return super().dispatch(request, *args, **kwargs)

    def _ensure_user_oficina(self):
        if hasattr(self.request.user, 'oficina'):
            return self.request.user.oficina
        oficina = Oficina.objects.create(
            dono=self.request.user,
            nome=f'Oficina de {self.request.user.get_username()}',
        )
        self.request.user.oficina = oficina
        return oficina

    def test_func(self):
        return self.request.user.is_staff and hasattr(self.request.user, 'oficina')

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            logout(self.request)
        return redirect(self.login_url)

    @property
    def oficina(self):
        return self._ensure_user_oficina()


class BookingCreateView(FormView):
    template_name = 'agenda/booking_form.html'
    form_class = BookingForm
    success_url = reverse_lazy('agenda:booking_success')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['oficina'] = getattr(self.request, 'oficina', None)
        return kwargs

    def form_valid(self, form):
        booking = form.save(commit=False)
        booking.oficina = getattr(self.request, 'oficina', None) or form.cleaned_data['oficina']
        booking.save()
        # Envia notificação de WhatsApp em background (não bloqueia a resposta ao cliente)
        try:
            t = threading.Thread(target=enviar_whatsapp, args=(booking,))
            t.daemon = True
            t.start()
        except Exception:
            # Não interromper o fluxo de agendamento caso falhe iniciar o thread
            pass

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['service_durations'] = {
            'Troca de óleo': '30 minutos',
            'Alinhamento': '1 hora',
            'Balanceamento': '1 hora',
            'Revisão básica': '2 horas',
            'Revisão completa': '4 horas',
            'Diagnóstico eletrônico': '1 hora',
            'Serviço personalizado': 'Intervalo de tempo selecionável',
        }
        context['duration_help'] = {
            '30': '30 minutos',
            '60': '1 hora',
            '90': '1h 30min',
            '120': '2 horas',
            '240': '4 horas',
        }
        return context


class AvailableSlotsView(View):
    def get(self, request, *args, **kwargs):
        date_str = request.GET.get('date')
        duration_str = request.GET.get('duration')
        oficina_id = request.GET.get('oficina')
        if not date_str or not duration_str:
            return JsonResponse({
                'slots': [],
                'message': 'Informe data e duração para exibir horários disponíveis.',
            })

        try:
            scheduled_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            duration = int(duration_str)
        except (ValueError, TypeError):
            return JsonResponse({
                'slots': [],
                'message': 'Data ou duração inválida.',
            })

        if scheduled_date < date.today():
            return JsonResponse({
                'slots': [],
                'message': 'Não é possível agendar para datas passadas.',
            })

        oficina = getattr(request, 'oficina', None)
        if oficina is None:
            if not oficina_id:
                return JsonResponse({
                    'slots': [],
                    'message': 'Selecione a oficina para exibir horários disponíveis.',
                })
            try:
                oficina = Oficina.objects.get(pk=oficina_id)
            except (Oficina.DoesNotExist, ValueError, TypeError):
                return JsonResponse({
                    'slots': [],
                    'message': 'Oficina inválida.',
                })

        if Booking.available_minutes_for_date(scheduled_date, oficina=oficina) < duration:
            return JsonResponse({
                'slots': [],
                'message': 'Não há mais horários disponíveis para este dia.',
            })

        slots = Booking.available_start_times_for_date(scheduled_date, duration, oficina=oficina)
        if not slots:
            return JsonResponse({
                'slots': [],
                'message': 'Nenhum horário livre encontrado para a data e duração selecionadas.',
            })

        return JsonResponse({
            'slots': [slot.strftime('%H:%M') for slot in slots],
            'available_minutes': Booking.available_minutes_for_date(scheduled_date, oficina=oficina),
            'message': f'{len(slots)} horário(s) disponível(is).',
        })


class BookingSuccessView(TemplateView):
    template_name = 'agenda/booking_success.html'


class OrdemServicoListView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/os_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '')
        date_filter = self.request.GET.get('date', '')

        orders = OrdemServico.objects.select_related('booking').filter(oficina=self.oficina)
        if query:
            orders = orders.filter(
                Q(order_number__icontains=query)
                | Q(client_name__icontains=query)
                | Q(vehicle_brand__icontains=query)
                | Q(vehicle_model__icontains=query)
            )
        if status:
            orders = orders.filter(status=status)
        if date_filter:
            orders = orders.filter(scheduled_date=date_filter)

        status_summary = {choice[0]: 0 for choice in OrdemServico.Status.choices}
        totals = OrdemServico.objects.filter(oficina=self.oficina).values('status').annotate(total=Count('id'))
        for item in totals:
            status_summary[item['status']] = item['total']

        context.update({
            'orders': orders.order_by('-created_at'),
            'query': query,
            'status_filter': status,
            'date_filter': date_filter,
            'status_choices': OrdemServico.Status.choices,
            'status_summary': status_summary,
        })
        return context


class OrdemServicoDetailView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/os_detail_new.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        os_pk = self.kwargs.get('pk')
        ordem = get_object_or_404(OrdemServico, pk=os_pk, oficina=self.oficina)
        status_form = OrdemServicoStatusForm(initial={'status': ordem.status})
        financial_form = OrdemServicoFinancialForm(instance=ordem)
        service_form = OrdemServicoServiceItemForm()
        part_form = OrdemServicoPartItemForm()
        context.update({
            'ordem': ordem,
            'status_form': status_form,
            'financial_form': financial_form,
            'service_form': service_form,
            'part_form': part_form,
            'history': ordem.history.all(),
        })
        return context


class OrdemServicoServiceItemCreateView(StaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        form = OrdemServicoServiceItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.oficina = self.oficina
            item.ordem_servico = ordem
            item.save()
            ordem.service_value = sum(i.total_price for i in ordem.service_items.all())
            ordem.save()
            return redirect('agenda:os_detail', pk=pk)
        return redirect('agenda:os_detail', pk=pk)


class OrdemServicoServiceItemDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk, item_pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        item = get_object_or_404(OrdemServicoServiceItem, pk=item_pk, ordem_servico=ordem, oficina=self.oficina)
        item.delete()
        ordem.service_value = sum(i.total_price for i in ordem.service_items.all())
        ordem.save()
        return redirect('agenda:os_detail', pk=pk)


class OrdemServicoPartItemCreateView(StaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        form = OrdemServicoPartItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.oficina = self.oficina
            item.ordem_servico = ordem
            item.save()
            ordem.parts_value = sum(i.total_price for i in ordem.part_items.all())
            ordem.save()
            return redirect('agenda:os_detail', pk=pk)
        return redirect('agenda:os_detail', pk=pk)


class OrdemServicoPartItemDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk, item_pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        item = get_object_or_404(OrdemServicoPartItem, pk=item_pk, ordem_servico=ordem, oficina=self.oficina)
        item.delete()
        ordem.parts_value = sum(i.total_price for i in ordem.part_items.all())
        ordem.save()
        return redirect('agenda:os_detail', pk=pk)


class OrdemServicoFinancialUpdateView(StaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        form = OrdemServicoFinancialForm(request.POST, instance=ordem)
        if form.is_valid():
            form.save()
        return redirect('agenda:os_detail', pk=pk)


class OrdemServicoCreateFromBookingView(StaffRequiredMixin, View):
    def get(self, request, booking_id, *args, **kwargs):
        booking = get_object_or_404(Booking, pk=booking_id, oficina=self.oficina)
        if hasattr(booking, 'ordem_servico'):
            return redirect('agenda:os_detail', pk=booking.ordem_servico.pk)

        ordem = OrdemServico.objects.create(
            oficina=self.oficina,
            booking=booking,
            client_name=booking.full_name,
            phone=booking.phone,
            vehicle_brand=booking.vehicle_brand,
            vehicle_model=booking.vehicle_model,
            vehicle_year=booking.vehicle_year,
            plate='',
            problem_description=booking.problem_description,
            duration_minutes=booking.duration_minutes,
            scheduled_date=booking.scheduled_date,
            observations='',
            status=OrdemServico.Status.RECEBIDO,
        )
        return redirect('agenda:os_detail', pk=ordem.pk)


class OrdemServicoStatusUpdateView(StaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        form = OrdemServicoStatusForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            note = form.cleaned_data['note']
            if new_status != ordem.status:
                ordem.status = new_status
                ordem.save(user=request.user, note=note)
        return redirect('agenda:os_detail', pk=ordem.pk)


class OrdemServicoPrintView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/os_print.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        os_pk = self.kwargs.get('pk')
        ordem = get_object_or_404(OrdemServico, pk=os_pk, oficina=self.oficina)
        context['ordem'] = ordem
        return context


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '')
        date_filter = self.request.GET.get('date', '')

        bookings = Booking.objects.filter(oficina=self.oficina)
        if query:
            bookings = bookings.filter(
                Q(full_name__icontains=query)
                | Q(vehicle_brand__icontains=query)
                | Q(vehicle_model__icontains=query)
            )
        if status:
            bookings = bookings.filter(status=status)
        if date_filter:
            bookings = bookings.filter(scheduled_date=date_filter)

        bookings = bookings.order_by('-scheduled_date', 'start_time', 'full_name')
        
        # Implementar paginação
        paginator = Paginator(bookings, 10)
        page = self.request.GET.get('page')
        try:
            bookings_page = paginator.page(page)
        except PageNotAnInteger:
            bookings_page = paginator.page(1)
        except EmptyPage:
            bookings_page = paginator.page(paginator.num_pages)

        calendar_start = date.today()
        calendar_days = [calendar_start + timedelta(days=offset) for offset in range(7)]
        daily_summary = []
        for current_date in calendar_days:
            booked = Booking.booked_minutes_for_date(current_date, oficina=self.oficina)
            occupancy = round((booked / 480) * 100) if booked else 0
            daily_summary.append({
                'date': current_date,
                'booked': booked,
                'available': max(0, 480 - booked),
                'occupancy': occupancy,
                'intervals': Booking.occupied_intervals_for_date(current_date, oficina=self.oficina),
            })

        status_counts = Booking.objects.filter(oficina=self.oficina).values('status').annotate(total=Sum('duration_minutes'))
        status_map = {item['status']: item['total'] for item in status_counts}
        in_progress_count = Booking.objects.filter(oficina=self.oficina, status=Booking.Status.IN_PROGRESS).count()
        filter_params = self.request.GET.copy()
        filter_params.pop('page', None)

        selected_schedule = []
        if date_filter:
            try:
                selected_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
                selected_schedule = Booking.occupied_intervals_for_date(selected_date, oficina=self.oficina)
            except ValueError:
                selected_schedule = []

        context.update({
            'bookings': bookings_page,
            'paginator': paginator,
            'total_bookings': paginator.count,
            'calendar_days': calendar_days,
            'daily_summary': daily_summary,
            'status_totals': status_map,
            'in_progress_count': in_progress_count,
            'query': query,
            'status_filter': status,
            'date_filter': date_filter,
            'filter_querystring': filter_params.urlencode(),
            'selected_schedule': selected_schedule,
            'status_choices': Booking.Status.choices,
        })
        return context


class ExportBookingsExcelView(StaffRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '').strip()
        status = request.GET.get('status', '')
        date_filter = request.GET.get('date', '')

        bookings = Booking.objects.filter(oficina=self.oficina)
        if query:
            bookings = bookings.filter(
                Q(full_name__icontains=query)
                | Q(vehicle_brand__icontains=query)
                | Q(vehicle_model__icontains=query)
            )
        if status:
            bookings = bookings.filter(status=status)
        if date_filter:
            bookings = bookings.filter(scheduled_date=date_filter)

        bookings = bookings.order_by('-scheduled_date', 'start_time', 'full_name')

        # Criar workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Agendamentos"

        # Estilos
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Cabeçalhos
        headers = [
            'Nome',
            'Telefone',
            'Marca',
            'Modelo',
            'Ano',
            'Problema',
            'Tempo Estimado',
            'Data',
            'Horário',
            'Status'
        ]
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border

        # Adicionar dados
        for row_num, booking in enumerate(bookings, 2):
            data = [
                booking.full_name,
                booking.phone,
                booking.vehicle_brand,
                booking.vehicle_model,
                booking.vehicle_year,
                booking.problem_description,
                booking.duration_label,
                booking.scheduled_date.strftime('%d/%m/%Y'),
                booking.start_time.strftime('%H:%M'),
                booking.status_label,
            ]
            
            for col_num, value in enumerate(data, 1):
                cell = ws.cell(row=row_num, column=col_num)
                cell.value = value
                cell.border = border
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        # Ajustar largura das colunas
        column_widths = [20, 15, 15, 15, 8, 30, 18, 12, 10, 15]
        for col_num, width in enumerate(column_widths, 1):
            ws.column_dimensions[chr(64 + col_num)].width = width

        # Preparar resposta
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="agendamentos.xlsx"'
        wb.save(response)
        
        return response


class FinanceDashboardView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/finance_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date = self.request.GET.get('start_date', '')
        end_date = self.request.GET.get('end_date', '')
        client = self.request.GET.get('client', '').strip()
        vehicle = self.request.GET.get('vehicle', '').strip()
        mechanic = self.request.GET.get('mechanic', '').strip()
        status = self.request.GET.get('status', '')
        filter_querystring = self.request.GET.urlencode()

        orders = OrdemServico.objects.filter(oficina=self.oficina, status=OrdemServico.Status.COMPLETED)
        if start_date:
            orders = orders.filter(completed_at__date__gte=start_date)
        if end_date:
            orders = orders.filter(completed_at__date__lte=end_date)
        if client:
            orders = orders.filter(client_name__icontains=client)
        if vehicle:
            orders = orders.filter(Q(vehicle_brand__icontains=vehicle) | Q(vehicle_model__icontains=vehicle) | Q(plate__icontains=vehicle))
        if mechanic:
            orders = orders.filter(mechanic_name__icontains=mechanic)
        if status:
            orders = orders.filter(status=status)

        revenue_day = orders.filter(completed_at__date=date.today()).aggregate(total=Sum('total_value'))['total'] or 0
        revenue_week = orders.filter(completed_at__date__gte=date.today() - timedelta(days=7)).aggregate(total=Sum('total_value'))['total'] or 0
        revenue_month = orders.filter(completed_at__month=date.today().month, completed_at__year=date.today().year).aggregate(total=Sum('total_value'))['total'] or 0
        revenue_year = orders.filter(completed_at__year=date.today().year).aggregate(total=Sum('total_value'))['total'] or 0
        total_completed_os = orders.count()
        unique_clients = orders.values('client_name').distinct().count()
        unique_vehicles = orders.values('vehicle_brand', 'vehicle_model', 'plate').distinct().count()
        ticket_mean = orders.aggregate(avg=Avg('total_value'))['avg'] or 0

        revenue_total = orders.aggregate(total=Sum('total_value'))['total'] or 0
        services_done = orders.count()
        parts_total = orders.aggregate(total=Sum('parts_value'))['total'] or 0
        # removed estimated_profit aggregation

        top_services = OrdemServicoServiceItem.objects.filter(oficina=self.oficina).values('description').annotate(total=Sum(F('quantity'))).order_by('-total')[:5]
        top_parts = OrdemServicoPartItem.objects.filter(oficina=self.oficina).values('description').annotate(total=Sum(F('quantity'))).order_by('-total')[:5]

        daily_series = []
        for offset in range(7):
            day = date.today() - timedelta(days=6 - offset)
            amount = orders.filter(completed_at__date=day).aggregate(total=Sum('total_value'))['total'] or 0
            daily_series.append({'date': day.strftime('%d/%m'), 'amount': float(amount)})

        monthly_series = []
        for month_offset in range(6, -1, -1):
            current = date.today().replace(day=1) - timedelta(days=month_offset * 30)
            month_label = current.strftime('%b/%Y')
            amount = orders.filter(completed_at__month=current.month, completed_at__year=current.year).aggregate(total=Sum('total_value'))['total'] or 0
            monthly_series.append({'month': month_label, 'amount': float(amount)})

        service_vs_parts = [
            {'label': 'Serviços', 'value': float(orders.aggregate(total=Sum('service_value'))['total'] or 0)},
            {'label': 'Peças', 'value': float(parts_total)},
        ]

        transaction_filters = FinancialTransaction.objects.select_related('ordem_servico').filter(
            oficina=self.oficina,
            ordem_servico__isnull=False
        )
        if start_date:
            transaction_filters = transaction_filters.filter(due_date__gte=start_date)
        if end_date:
            transaction_filters = transaction_filters.filter(due_date__lte=end_date)
        if client:
            transaction_filters = transaction_filters.filter(ordem_servico__client_name__icontains=client)
        if vehicle:
            transaction_filters = transaction_filters.filter(
                Q(ordem_servico__vehicle_brand__icontains=vehicle)
                | Q(ordem_servico__vehicle_model__icontains=vehicle)
                | Q(ordem_servico__plate__icontains=vehicle)
            )
        if mechanic:
            transaction_filters = transaction_filters.filter(ordem_servico__mechanic_name__icontains=mechanic)
        if status:
            transaction_filters = transaction_filters.filter(ordem_servico__status=status)

        pending_alerts = transaction_filters.filter(status='pending', due_date__lt=date.today()).count()
        receivables = transaction_filters.filter(transaction_type='receivable').order_by('-due_date')[:15]
        payables = transaction_filters.filter(transaction_type='payable').order_by('-due_date')[:15]
        cashflow_balance = CashFlowRecord.objects.filter(oficina=self.oficina).aggregate(balance=Sum(Case(When(entry_type='inflow', then=F('amount')), When(entry_type='outflow', then=F('amount') * Value(-1)), default=Value(0), output_field=DecimalField())))['balance'] or 0

        context.update({
            'start_date': start_date,
            'end_date': end_date,
            'client': client,
            'vehicle': vehicle,
            'mechanic': mechanic,
            'status_filter': status,
            'filter_querystring': filter_querystring,
            'status_choices': OrdemServico.Status.choices,
            'revenue_day': revenue_day,
            'revenue_week': revenue_week,
            'revenue_month': revenue_month,
            'revenue_year': revenue_year,
            'total_completed_os': total_completed_os,
            'ticket_mean': ticket_mean,
            'unique_clients': unique_clients,
            'unique_vehicles': unique_vehicles,
            'revenue_total': revenue_total,
            'services_done': services_done,
            'parts_total': parts_total,
            'top_services': list(top_services),
            'top_parts': list(top_parts),
            'daily_series': daily_series,
            'monthly_series': monthly_series,
            'service_vs_parts': service_vs_parts,
            'pending_alerts': pending_alerts,
            'receivables': receivables,
            'payables': payables,
            'cashflow_balance': cashflow_balance,
        })
        return context


class FinanceExportExcelView(StaffRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        client = request.GET.get('client', '').strip()
        vehicle = request.GET.get('vehicle', '').strip()
        mechanic = request.GET.get('mechanic', '').strip()
        status = request.GET.get('status', '')

        orders = OrdemServico.objects.filter(oficina=self.oficina, status=OrdemServico.Status.COMPLETED)
        if start_date:
            orders = orders.filter(completed_at__date__gte=start_date)
        if end_date:
            orders = orders.filter(completed_at__date__lte=end_date)
        if client:
            orders = orders.filter(client_name__icontains=client)
        if vehicle:
            orders = orders.filter(Q(vehicle_brand__icontains=vehicle) | Q(vehicle_model__icontains=vehicle) | Q(plate__icontains=vehicle))
        if mechanic:
            orders = orders.filter(mechanic_name__icontains=mechanic)
        if status:
            orders = orders.filter(status=status)

        wb = Workbook()
        ws = wb.active
        ws.title = 'Financeiro'

        headers = [
            'OS', 'Cliente', 'Veículo', 'Placa', 'Mecânico', 'Data Conclusão', 'Serviços', 'Peças', 'Total', 'Status', 'Pagamento'
        ]
        header_font = Font(bold=True, color='FFFFFF', size=12)
        header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = header_alignment

        for row_num, ordem in enumerate(orders, 2):
            row = [
                ordem.order_number,
                ordem.client_name,
                f'{ordem.vehicle_brand} {ordem.vehicle_model}',
                ordem.plate,
                ordem.mechanic_name,
                ordem.completed_at.strftime('%d/%m/%Y %H:%M') if ordem.completed_at else '',
                float(ordem.service_value),
                float(ordem.parts_value),
                float(ordem.total_value),
                ordem.status_label,
                ordem.payment_method,
            ]
            for col_num, value in enumerate(row, 1):
                cell = ws.cell(row=row_num, column=col_num)
                cell.value = value
                cell.border = border
                cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)

        widths = [14, 25, 20, 12, 18, 18, 12, 12, 12, 14, 16]
        for col_num, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + col_num)].width = width

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="relatorio_financeiro.xlsx"'
        wb.save(response)
        return response


class FinanceExportPdfView(StaffRequiredMixin, View):
    def get(self, request, pk, *args, **kwargs):
        ordem = get_object_or_404(OrdemServico, pk=pk, oficina=self.oficina)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="cupom_{ordem.order_number}.pdf"'

        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm

        buffer = response
        document = canvas.Canvas(buffer, pagesize=A4)
        document.setFont('Helvetica-Bold', 14)
        document.drawString(30 * mm, 280 * mm, 'Oficina PRO')
        document.setFont('Helvetica', 10)
        document.drawString(30 * mm, 273 * mm, 'Endereço: Rua Exemplo, 123 - Cidade')
        document.drawString(30 * mm, 267 * mm, 'Telefone: (11) 99999-9999 - WhatsApp: (11) 98888-8888')
        document.line(30 * mm, 264 * mm, 180 * mm, 264 * mm)
        y = 258 * mm
        document.setFont('Helvetica-Bold', 12)
        document.drawString(30 * mm, y, f'Cupom de Serviço - {ordem.order_number}')
        y -= 8 * mm
        document.setFont('Helvetica', 10)
        document.drawString(30 * mm, y, f'Data/Hora: {ordem.completed_at.strftime("%d/%m/%Y %H:%M") if ordem.completed_at else "-"}')
        y -= 8 * mm
        document.drawString(30 * mm, y, f'Cliente: {ordem.client_name}')
        y -= 8 * mm
        document.drawString(30 * mm, y, f'Veículo: {ordem.vehicle_brand} {ordem.vehicle_model} - {ordem.plate}')
        y -= 8 * mm
        document.drawString(30 * mm, y, f'Quilometragem: {ordem.mileage or "-"}')
        y -= 12 * mm
        document.setFont('Helvetica-Bold', 11)
        document.drawString(30 * mm, y, 'Serviços executados:')
        y -= 8 * mm
        document.setFont('Helvetica', 10)
        if ordem.service_items.exists():
            for item in ordem.service_items.all():
                document.drawString(32 * mm, y, f'{item.description} x{item.quantity} - R$ {item.total_price:.2f}')
                y -= 7 * mm
                if y < 30 * mm:
                    document.showPage()
                    y = 280 * mm
        else:
            document.drawString(32 * mm, y, '- Nenhum serviço registrado -')
            y -= 7 * mm
        y -= 4 * mm
        document.setFont('Helvetica-Bold', 11)
        document.drawString(30 * mm, y, 'Peças utilizadas:')
        y -= 8 * mm
        document.setFont('Helvetica', 10)
        if ordem.part_items.exists():
            for item in ordem.part_items.all():
                document.drawString(32 * mm, y, f'{item.description} x{item.quantity} - R$ {item.total_price:.2f}')
                y -= 7 * mm
                if y < 30 * mm:
                    document.showPage()
                    y = 280 * mm
        else:
            document.drawString(32 * mm, y, '- Nenhuma peça registrada -')
            y -= 7 * mm
        y -= 8 * mm
        document.setFont('Helvetica-Bold', 11)
        document.drawString(30 * mm, y, f'Total serviços: R$ {ordem.service_value:.2f}')
        y -= 7 * mm
        document.drawString(30 * mm, y, f'Total peças: R$ {ordem.parts_value:.2f}')
        y -= 7 * mm
        document.drawString(30 * mm, y, f'Valor total: R$ {ordem.total_value:.2f}')
        y -= 7 * mm
        document.drawString(30 * mm, y, f'Pagamento: {ordem.get_payment_method_display() if ordem.payment_method else "-"}')
        y -= 7 * mm
        document.drawString(30 * mm, y, f'Mecânico: {ordem.mechanic_name or "-"}')
        y -= 7 * mm
        document.drawString(30 * mm, y, f'Garantia: {ordem.warranty}')
        y -= 12 * mm
        document.setFont('Helvetica', 9)
        document.drawString(30 * mm, y, f'Observações: {ordem.observations or "-"}')
        document.showPage()
        document.save()
        return response


class FinanceInvoiceView(StaffRequiredMixin, TemplateView):
    template_name = 'agenda/finance_invoice.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        os_pk = self.kwargs.get('pk')
        ordem = get_object_or_404(OrdemServico, pk=os_pk, oficina=self.oficina)
        context['ordem'] = ordem
        return context


class BookingStatusUpdateView(StaffRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking_id = request.POST.get('booking_id')
        new_status = request.POST.get('status')
        booking = get_object_or_404(Booking, pk=booking_id, oficina=self.oficina)
        if new_status in Booking.Status.values:
            booking.status = new_status
            booking.save()
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('agenda:dashboard')))


class DeleteBookingView(StaffRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking_id = request.POST.get('booking_id')
        booking = get_object_or_404(Booking, pk=booking_id, oficina=self.oficina)
        booking.delete()
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('agenda:dashboard')))
