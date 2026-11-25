/** "₹1,23,456.00" / "$1,234.00": each currency in its usual number format. */
export const money = (amount, currency) =>
  new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", { style: "currency", currency }).format(amount);
