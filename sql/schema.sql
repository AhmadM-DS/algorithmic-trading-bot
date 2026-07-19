CREATE TABLE Orders
(
    Order_ID INT IDENTITY(1,1) PRIMARY KEY,
    Alpaca_Order_ID NVARCHAR(50) NOT NULL,
    Ticker NVARCHAR(5) NOT NULL,
    Side NVARCHAR(4) NOT NULL,
    Quantity INT NOT NULL,
    Price DECIMAL(10, 2) NOT NULL,
    [Status] NVARCHAR(25) NOT NULL,
    Profit DECIMAL(10, 2),
    [Date] DATETIME2 NOT NULL,
    CONSTRAINT UQ_Alpaca_Order_ID UNIQUE (Alpaca_Order_ID)
);
GO
CREATE TABLE Trades
(
    Trade_ID INT IDENTITY(1,1) PRIMARY KEY,
    Strategy NVARCHAR(50) NOT NULL,
    Trade_Type NVARCHAR(25) NOT NULL DEFAULT 'Backtest',
    Ticker NVARCHAR(5) NOT NULL,
    Side NVARCHAR(4) NOT NULL,
    Quantity INT NOT NULL,
    Price DECIMAL(10, 2) NOT NULL,
    Profit DECIMAL(10, 2),
    [Date] DATETIME2 NOT NULL,
    Order_ID INT NULL,
    CONSTRAINT FK_Orders
        FOREIGN KEY (Order_ID) REFERENCES Orders(Order_ID)
);
GO
CREATE TABLE Metrics
(
    Metric_ID INT IDENTITY(1,1) PRIMARY KEY,
    Strategy NVARCHAR(50) NOT NULL,
    Ticker NVARCHAR(5) NOT NULL,
    Starting_Capital DECIMAL(10, 2) NOT NULL,
    Final_Capital DECIMAL(10, 2) NOT NULL,
    Percent_Return DECIMAL(10, 2) NOT NULL,
    Win_Rate DECIMAL(5, 2) NOT NULL,
    Risk_Reward DECIMAL(10, 2),
    [Date] DATETIME2 NOT NULL
);
GO
CREATE TABLE Subscriptions
(
    Subscription_ID INT IDENTITY(1,1) PRIMARY KEY,
    [Service_Name] NVARCHAR(50) NOT NULL,
    [Provider] NVARCHAR(50) NOT NULL,
    Purpose NVARCHAR(250),
    Cost DECIMAL(10, 2) NOT NULL,
    Billing_Cycle NVARCHAR(25) NOT NULL,
    Payment_Method NVARCHAR(50) NOT NULL,
    [Start_Date] DATE NOT NULL,
    End_Date DATE NULL,
    Is_Active BIT NOT NULL DEFAULT 1
);
GO
CREATE TABLE Expenses
(
    Expense_ID INT IDENTITY(1,1) PRIMARY KEY,
    Expense_Name NVARCHAR(50) NOT NULL,
    [Provider] NVARCHAR(50) NOT NULL,
    Purpose NVARCHAR(250),
    Cost DECIMAL(10, 2) NOT NULL,
    Payment_Method NVARCHAR(50) NOT NULL,
    [Date] DATE NOT NULL,
    Subscription_ID INT NULL,
    CONSTRAINT FK_Subscription
        FOREIGN KEY (Subscription_ID) REFERENCES Subscriptions(Subscription_ID)
);
GO
CREATE TABLE PaymentMethods
(
    Payment_Method_ID INT IDENTITY(1,1) PRIMARY KEY,
    [Name] NVARCHAR(50) NOT NULL,
    CONSTRAINT UQ_PaymentMethod_Name UNIQUE ([Name])
);
GO
CREATE TABLE BotStatus
(
    Bot_Status_ID INT NOT NULL PRIMARY KEY,
    Last_Heartbeat DATETIME2 NOT NULL
);
GO