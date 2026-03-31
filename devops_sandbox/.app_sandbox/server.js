const express = require('express');
const config = require('./config.json');

const app = express();
app.use(express.json());

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime() });
});

// Mount route modules
const usersRouter = require('./routes/users');
const dataRouter = require('./routes/data');

app.use('/api/users', usersRouter);
app.use('/api/data', dataRouter);

// Start server on the port from config
const PORT = config.port;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on port ${PORT}`);
});
