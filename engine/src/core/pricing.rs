use super::types::{Cents, FulfillmentOption, LineItem, Product, Total};

/// Calculate a line item from a product and quantity.
/// All math in integer cents — no floating point.
pub fn calculate_line_item(product: &Product, quantity: u32, line_item_id: &str) -> LineItem {
    let base_amount = product.base_price * quantity as u64;
    let discount: Cents = 0; // MVP: no discounts
    let subtotal = base_amount - discount;
    let tax: Cents = 0; // tax calculated at session level, not per line item
    let total = subtotal + tax;

    LineItem {
        id: line_item_id.into(),
        product_id: product.id.clone(),
        quantity,
        base_amount,
        discount,
        subtotal,
        tax,
        total,
    }
}

/// Calculate tax based on shipping state.
/// CA = 10%, all others = 0%. Returns tax in cents.
pub fn calculate_tax(taxable_amount: Cents, state: Option<&str>) -> Cents {
    match state {
        Some("CA") => (taxable_amount * 10 + 50) / 100, // round to nearest cent
        _ => 0,
    }
}

/// Build the totals array for a checkout session.
pub fn calculate_totals(
    line_items: &[LineItem],
    fulfillment: Option<&FulfillmentOption>,
    state: Option<&str>,
) -> Vec<Total> {
    let items_base: Cents = line_items.iter().map(|li| li.base_amount).sum();
    let items_discount: Cents = line_items.iter().map(|li| li.discount).sum();
    let subtotal = items_base - items_discount;
    let fulfillment_cost = fulfillment.map_or(0, |f| f.total);
    let taxable = subtotal + fulfillment_cost;
    let tax = calculate_tax(taxable, state);
    let total = subtotal + fulfillment_cost + tax;

    let mut totals = vec![Total {
        total_type: "items_base_amount".into(),
        display_text: format!("Items ({})", line_items.len()),
        amount: items_base,
    }];

    if items_discount > 0 {
        totals.push(Total {
            total_type: "items_discount".into(),
            display_text: "Discount".into(),
            amount: items_discount,
        });
    }

    totals.push(Total {
        total_type: "subtotal".into(),
        display_text: "Subtotal".into(),
        amount: subtotal,
    });

    if fulfillment_cost > 0 {
        totals.push(Total {
            total_type: "fulfillment".into(),
            display_text: fulfillment
                .map(|f| f.title.clone())
                .unwrap_or_else(|| "Shipping".into()),
            amount: fulfillment_cost,
        });
    }

    if tax > 0 {
        totals.push(Total {
            total_type: "tax".into(),
            display_text: "Tax".into(),
            amount: tax,
        });
    }

    totals.push(Total {
        total_type: "total".into(),
        display_text: "Total".into(),
        amount: total,
    });

    totals
}

/// Generate default fulfillment options for items that require shipping.
pub fn default_fulfillment_options() -> Vec<FulfillmentOption> {
    vec![
        FulfillmentOption {
            id: "ship_standard".into(),
            fulfillment_type: "shipping".into(),
            title: "Standard Shipping".into(),
            subtitle: Some("5-7 business days".into()),
            carrier: Some("USPS".into()),
            subtotal: 500,
            tax: 0,
            total: 500,
        },
        FulfillmentOption {
            id: "ship_express".into(),
            fulfillment_type: "shipping".into(),
            title: "Express Shipping".into(),
            subtitle: Some("2-3 business days".into()),
            carrier: Some("UPS".into()),
            subtotal: 1500,
            tax: 0,
            total: 1500,
        },
        FulfillmentOption {
            id: "digital".into(),
            fulfillment_type: "digital".into(),
            title: "Digital Delivery".into(),
            subtitle: Some("Instant".into()),
            carrier: None,
            subtotal: 0,
            tax: 0,
            total: 0,
        },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_product() -> Product {
        Product {
            id: "prod_1".into(),
            name: "Widget".into(),
            description: "A fine widget".into(),
            base_price: 2000, // $20.00
            category: "electronics".into(),
            available_quantity: 100,
            requires_shipping: true,
            image_url: None,
        }
    }

    #[test]
    fn line_item_calculation() {
        let p = sample_product();
        let li = calculate_line_item(&p, 3, "li_1");
        assert_eq!(li.base_amount, 6000);
        assert_eq!(li.discount, 0);
        assert_eq!(li.subtotal, 6000);
        assert_eq!(li.total, 6000);
    }

    #[test]
    fn tax_california() {
        assert_eq!(calculate_tax(10000, Some("CA")), 1000); // 10% of $100
        assert_eq!(calculate_tax(10000, Some("TX")), 0);
        assert_eq!(calculate_tax(10000, None), 0);
    }

    #[test]
    fn totals_with_shipping_and_tax() {
        let p = sample_product();
        let items = vec![calculate_line_item(&p, 2, "li_1")]; // $40.00
        let shipping = FulfillmentOption {
            id: "s".into(),
            fulfillment_type: "shipping".into(),
            title: "Standard".into(),
            subtitle: None,
            carrier: None,
            subtotal: 500,
            tax: 0,
            total: 500,
        };
        let totals = calculate_totals(&items, Some(&shipping), Some("CA"));
        let total = totals.iter().find(|t| t.total_type == "total").unwrap();
        // $40 + $5 shipping = $45 taxable, 10% = $4.50 tax, total = $49.50
        assert_eq!(total.amount, 4950);
    }
}
