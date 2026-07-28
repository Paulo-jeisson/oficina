from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .booking_workflow import create_booking
from .models import Booking, EstoqueItem, Oficina, OrdemServico
from .stock import move_stock


@skipUnless(connection.vendor == 'postgresql', 'Requer locks reais do PostgreSQL.')
class PostgreSQLConcurrencyTestCase(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user('pg-owner', password='test')
        self.oficina = Oficina.objects.create(
            nome='Oficina PostgreSQL',
            dono=self.user,
            mechanic_count='1',
        )

    def _booking(self, suffix):
        return Booking(
            oficina_id=self.oficina.pk,
            full_name=f'Cliente {suffix}',
            phone='11999999999',
            vehicle_brand='Fiat',
            vehicle_model='Uno',
            vehicle_year=2020,
            problem_description='Teste concorrente',
            service_type='custom',
            duration_minutes=60,
            scheduled_date=date(2030, 1, 10),
            start_time=time(8),
        )

    def test_same_slot_has_only_one_winner(self):
        barrier = Barrier(2)

        def reserve(suffix):
            close_old_connections()
            barrier.wait()
            try:
                booking = create_booking(self._booking(suffix))
                return ('created', booking.pk)
            except ValidationError:
                return ('conflict', None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, ('A', 'B')))

        self.assertEqual([result[0] for result in results].count('created'), 1)
        self.assertEqual([result[0] for result in results].count('conflict'), 1)
        self.assertEqual(Booking.objects.count(), 1)

    def test_order_numbers_are_unique_under_concurrency(self):
        bookings = []
        for suffix in ('A', 'B'):
            booking = self._booking(suffix)
            booking.start_time = time(8 if suffix == 'A' else 10)
            booking.assigned_box = 1
            booking.save()
            bookings.append(booking.pk)
        barrier = Barrier(2)

        def create_order(booking_id):
            close_old_connections()
            barrier.wait()
            booking = Booking.objects.get(pk=booking_id)
            order = OrdemServico.objects.create(
                oficina_id=self.oficina.pk,
                booking=booking,
                client_name=booking.full_name,
                phone=booking.phone,
                vehicle_brand=booking.vehicle_brand,
                vehicle_model=booking.vehicle_model,
                vehicle_year=booking.vehicle_year,
                problem_description=booking.problem_description,
                duration_minutes=booking.duration_minutes,
                scheduled_date=booking.scheduled_date,
            )
            connection.close()
            return order.order_number

        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(create_order, bookings))

        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(OrdemServico.objects.count(), 2)

    def test_stock_cannot_become_negative_under_concurrency(self):
        item = EstoqueItem.objects.create(
            oficina=self.oficina,
            nome='Item concorrente',
            codigo='PG-LOCK',
            quantidade=10,
            custo_unitario=Decimal('1.00'),
            preco_venda=Decimal('2.00'),
        )
        barrier = Barrier(2)

        def consume(_):
            close_old_connections()
            barrier.wait()
            try:
                move_stock(
                    item=EstoqueItem.objects.get(pk=item.pk),
                    quantity=7,
                    movement_type='exit',
                )
                return 'moved'
            except ValidationError:
                return 'rejected'
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(consume, (1, 2)))

        item.refresh_from_db()
        self.assertEqual(results.count('moved'), 1)
        self.assertEqual(results.count('rejected'), 1)
        self.assertEqual(item.quantidade, 3)
