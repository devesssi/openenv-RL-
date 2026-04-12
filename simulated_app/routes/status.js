const express = require('express');
const router = express.Router();
const os = require('os');

router.get('/', (req, res) => {
  res.json({
    status: 'operational',
    hostname: os.hostname(),
    platform: os.platform(),
    memory: {
      total: Math.round(os.totalmem() / 1024 / 1024),
      free: Math.round(os.freemem() / 1024 / 1024),
      unit: 'MB'
    },
    uptime: Math.round(os.uptime()),
    nodeVersion: process.version
  });
});

module.exports = router;
