from dotenv import load_dotenv

from data_connector import AlpacaDataConnector

load_dotenv()

def main():
	# Ensure ALPACA_API_KEY and ALPACA_SECRET_KEY are set in your environment
	conn = AlpacaDataConnector()

	print("Downloading historical data for AAPL (daily)...")
	df = conn.get_historical("AAPL", start="2026-01-01", timeframe="1Day", limit=100)
	print(df.head())

	def on_quote(q):
		sym = q.get("symbol") or "?"
		bid = q.get("bid")
		ask = q.get("ask")
		print(f"Quote {sym} bid={bid} ask={ask}")

	print("Starting realtime quote stream for AAPL (30s)...")
	conn.start_stream("AAPL", on_quote=on_quote, run_seconds=30)


if __name__ == "__main__":
	main()


