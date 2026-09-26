from birdseye import eye


@eye
def summarize_orders(orders, tax_rate):
    totals = []
    for order in orders:
        subtotal = sum(item['price'] * item['quantity'] for item in order['items'])
        total = round(subtotal * (1 + tax_rate), 2)
        totals.append(dict(customer=order['customer'], subtotal=subtotal, total=total))

    grand_total = round(sum(order['total'] for order in totals), 2)
    return dict(orders=totals, grand_total=grand_total)


@eye
def divide(numerator, denominator):
    return numerator / denominator


if __name__ == '__main__':
    sample_orders = [
        dict(customer='Ada', items=[dict(price=12.50, quantity=2), dict(price=3.75, quantity=4)]),
        dict(customer='Linus', items=[dict(price=99.99, quantity=1), dict(price=4.25, quantity=3)]),
    ]

    print(summarize_orders(sample_orders, 0.0825))
    try:
        divide(7, 0)
    except ZeroDivisionError:
        print('Captured expected ZeroDivisionError')
