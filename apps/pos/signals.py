# Stock movements for sales are logged explicitly in the checkout view
# (apps/pos/views.py), at the point where the FIFO batch deduction happens.
# Logging them again here on SaleItem post_save would double-count every OUT
# movement in the inventory/audit logs, so no signal handlers are registered.
