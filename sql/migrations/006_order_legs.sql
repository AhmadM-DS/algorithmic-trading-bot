ALTER TABLE orders ADD parent_order_id INT NULL
    CONSTRAINT fk_orders_parent_order_id REFERENCES orders (order_id);
GO

CREATE INDEX ix_orders_parent_order_id ON orders (parent_order_id);
GO

INSERT INTO skip_reasons (skip_reason_id, code, [description], [priority])
VALUES
    (17, 'invalid_exit_prices', 'Stop or target on the wrong side of the price', 160);
GO
