const fs = require('fs');
const path = require('path');

module.exports = function loadEnv(envPath) {
    envPath = envPath || path.join(__dirname, '..', '..', '.env');
    const env = {};
    fs.readFileSync(envPath, 'utf8').split('\n').forEach(line => {
        line = line.trim();
        if (line && !line.startsWith('#')) {
            const [key, ...val] = line.split('=');
            env[key.trim()] = val.join('=').trim();
        }
    });
    return env;
};
