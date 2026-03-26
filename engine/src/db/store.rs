use rusqlite::{Connection, params};

use crate::core::error::{EngineError, Result};
use crate::core::types::{CheckoutSession, Product, TransactionRecord};

pub struct Store {
    conn: Connection,
}

impl Store {
    pub fn new(path: &str) -> Result<Self> {
        let conn = Connection::open(path).map_err(EngineError::Database)?;
        let store = Self { conn };
        store.init_tables()?;
        Ok(store)
    }

    fn init_tables(&self) -> Result<()> {
        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                currency TEXT NOT NULL,
                protocol TEXT NOT NULL,
                agent_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                protocol TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                fee INTEGER NOT NULL,
                execution_us INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_price INTEGER NOT NULL,
                category TEXT NOT NULL,
                available_quantity INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            ",
            )
            .map_err(EngineError::Database)?;
        Ok(())
    }

    pub fn save_session(&self, session: &CheckoutSession) -> Result<()> {
        let data =
            serde_json::to_string(session).map_err(|e| EngineError::Internal(e.to_string()))?;
        let status = serde_json::to_value(&session.status)
            .map_err(|e| EngineError::Internal(e.to_string()))?;
        let status_str = status.as_str().unwrap_or("unknown");
        let agent_id = session.agent_id.as_deref().unwrap_or("");
        let created_at = session.created_at.to_rfc3339();
        let updated_at = session.updated_at.to_rfc3339();

        self.conn
            .execute(
                "INSERT INTO sessions (id, status, currency, protocol, agent_id, data, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
                 ON CONFLICT(id) DO UPDATE SET
                     status = excluded.status,
                     currency = excluded.currency,
                     protocol = excluded.protocol,
                     agent_id = excluded.agent_id,
                     data = excluded.data,
                     updated_at = excluded.updated_at",
                params![
                    session.id,
                    status_str,
                    session.currency,
                    session.protocol,
                    agent_id,
                    data,
                    created_at,
                    updated_at,
                ],
            )
            .map_err(EngineError::Database)?;
        Ok(())
    }

    pub fn get_session(&self, id: &str) -> Result<Option<CheckoutSession>> {
        let mut stmt = self
            .conn
            .prepare("SELECT data FROM sessions WHERE id = ?1")
            .map_err(EngineError::Database)?;
        let mut rows = stmt
            .query_map(params![id], |row| {
                let data: String = row.get(0)?;
                Ok(data)
            })
            .map_err(EngineError::Database)?;

        match rows.next() {
            Some(Ok(data)) => {
                let session: CheckoutSession = serde_json::from_str(&data)
                    .map_err(|e| EngineError::Internal(e.to_string()))?;
                Ok(Some(session))
            }
            Some(Err(e)) => Err(EngineError::Database(e)),
            None => Ok(None),
        }
    }

    pub fn save_transaction(&self, tx: &TransactionRecord) -> Result<()> {
        let created_at = tx.created_at.to_rfc3339();
        self.conn
            .execute(
                "INSERT INTO transactions (id, session_id, protocol, agent_id, amount, fee, execution_us, status, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
                 ON CONFLICT(id) DO NOTHING",
                params![
                    tx.id,
                    tx.session_id,
                    tx.protocol,
                    tx.agent_id,
                    tx.amount,
                    tx.fee,
                    tx.execution_us,
                    tx.status,
                    created_at,
                ],
            )
            .map_err(EngineError::Database)?;
        Ok(())
    }

    pub fn get_transactions(&self, limit: u32) -> Result<Vec<TransactionRecord>> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, session_id, protocol, agent_id, amount, fee, execution_us, status, created_at
                 FROM transactions ORDER BY created_at DESC LIMIT ?1",
            )
            .map_err(EngineError::Database)?;

        let rows = stmt
            .query_map(params![limit], |row| {
                let created_at_str: String = row.get(8)?;
                let created_at = chrono::DateTime::parse_from_rfc3339(&created_at_str)
                    .map(|dt| dt.with_timezone(&chrono::Utc))
                    .unwrap_or_else(|_| chrono::Utc::now());
                Ok(TransactionRecord {
                    id: row.get(0)?,
                    session_id: row.get(1)?,
                    protocol: row.get(2)?,
                    agent_id: row.get(3)?,
                    amount: row.get(4)?,
                    fee: row.get(5)?,
                    execution_us: row.get(6)?,
                    status: row.get(7)?,
                    created_at,
                })
            })
            .map_err(EngineError::Database)?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row.map_err(EngineError::Database)?);
        }
        Ok(results)
    }

    pub fn save_product(&self, product: &Product) -> Result<()> {
        let data =
            serde_json::to_string(product).map_err(|e| EngineError::Internal(e.to_string()))?;
        self.conn
            .execute(
                "INSERT INTO products (id, name, base_price, category, available_quantity, data)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                 ON CONFLICT(id) DO UPDATE SET
                     name = excluded.name,
                     base_price = excluded.base_price,
                     category = excluded.category,
                     available_quantity = excluded.available_quantity,
                     data = excluded.data",
                params![
                    product.id,
                    product.name,
                    product.base_price,
                    product.category,
                    product.available_quantity,
                    data,
                ],
            )
            .map_err(EngineError::Database)?;
        Ok(())
    }
}
