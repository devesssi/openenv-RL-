const express = require('express');
const config = require('./config.json');
const { requestLogger } = require('./middleware/logger');
const { rateLimiter } = require('./middleware/rateLimit');

const app = express();
app.use(express.json());
app.use(requestLogger);
app.use(rateLimiter);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime(), version: config.version });
});

// Mount routes
const usersRouter = require('./routes/users');
const dataRouter = require('./routes/data');
const statusRouter = require('./routes/status');

app.use('/api/users', usersRouter);
app.use('/api/data', dataRouter);
app.use('/api/status', statusRouter);

// Error handling middleware
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.message}`);
  res.status(500).json({ error: 'Internal server error' });
});

// Start server
const PORT = config.port;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on port ${PORT}`);
});
