INSERT INTO skip_reasons (skip_reason_id, code, [description], [priority])
VALUES 
    (18, 'market_closed', 'Market is closed', 170),
    (19, 'too_late_to_buy', 'Too close to the close for a new buy', 180),
    (20, 'not_tradable', 'Alpaca can''t trade this ticker', 190),
    (21, 'open_order', 'An order for this is already out', 200),
    (22, 'stale_price', 'No recent trade to check the price against', 210),
    (23, 'price_moved', 'Price moved too far since the signal', 220);
GO

CREATE TABLE order_reviews
(
    order_review_id INT IDENTITY(1, 1) NOT NULL,
    signal_id INT NOT NULL,
    signal_price DECIMAL(19, 4) NOT NULL,
    check_price DECIMAL(19, 4) NULL,
    check_price_at DATETIME2 NULL,
    price_feed NVARCHAR(10) NOT NULL,
    price_move DECIMAL(10, 6) NULL,
    max_price_move DECIMAL(10, 6) NOT NULL,
    reviewed_at DATETIME2 NOT NULL CONSTRAINT df_order_reviews_reviewed_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_order_reviews_order_review_id PRIMARY KEY (order_review_id),
    CONSTRAINT fk_order_reviews_signal_id FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    CONSTRAINT uq_order_reviews_signal_id UNIQUE (signal_id),
    CONSTRAINT ck_order_reviews_signal_price CHECK (signal_price > 0),
    CONSTRAINT ck_order_reviews_max_price_move CHECK (max_price_move > 0),
    CONSTRAINT ck_order_reviews_check_price CHECK (check_price > 0),
    CONSTRAINT ck_order_reviews_price_feed CHECK (price_feed IN ('sip', 'iex')),
    CONSTRAINT ck_order_reviews_check_price_check_price_at_price_move CHECK (
        (check_price IS NOT NULL AND check_price_at IS NOT NULL AND price_move IS NOT NULL)
        OR
        (check_price IS NULL AND check_price_at IS NULL AND price_move IS NULL)
    )
);
GO

GRANT INSERT ON dbo.order_reviews TO bot_role;
GO

DENY UPDATE, DELETE ON dbo.order_reviews TO bot_role;
GO