const fs = require('fs');
const yaml = require('js-yaml');
const Ajv = require('ajv');

function fail(msg) {
  console.error('CONTRACT VALIDATION ERROR:');
  if (Array.isArray(msg)) msg.forEach(m => console.error('-', m));
  else console.error('-', msg);
  process.exit(2);
}

try {
  const contractPath = process.argv[2] || '../capability-contract.yaml';
  const raw = fs.readFileSync(contractPath, 'utf8');
  let doc;
  try { doc = yaml.load(raw); } catch (e) { fail('YAML parse error: ' + e.message); }

  // Basic JSON Schema to enforce required contract shape
  const schema = {
    type: 'object',
    required: ['name', 'version', 'contract'],
    properties: {
      name: { type: 'string' },
      version: { type: 'string' },
      contract: {
        type: 'object',
        required: ['api', 'inputSchema', 'outputSchema'],
        properties: {
          api: { type: 'object', required: ['endpoint'], properties: { endpoint: { type: 'string' } } },
          inputSchema: { type: 'object' },
          outputSchema: { type: 'object' }
        }
      }
    }
  };

  const ajv = new Ajv({ allErrors: true, strict: false });
  const validate = ajv.compile(schema);
  const valid = validate(doc);
  if (!valid) {
    const errs = validate.errors.map(e => `${e.instancePath || '/'} ${e.message}`);
    fail(errs);
  }

  // business-level checks
  const inputRequired = doc.contract.inputSchema && doc.contract.inputSchema.required;
  if (!Array.isArray(inputRequired) || !inputRequired.includes('idempotencyKey')) {
    fail('inputSchema.required must include idempotencyKey');
  }

  console.log('Contract validation passed (AJV)');
  // validate mock fixtures against outputSchema if present
  try {
    const mockBehaviors = (doc.tests && doc.tests.mockBehavior) || [];
    if (mockBehaviors.length > 0 && doc.contract && doc.contract.outputSchema) {
      const outSchema = doc.contract.outputSchema;
      const ajvOut = new Ajv({ allErrors: true, strict: false });
      const validateOut = ajvOut.compile(outSchema);
      const errors = [];
      for (const mb of mockBehaviors) {
        if (mb.responseFixture) {
          const fixturePath = mb.responseFixture;
          let fixtureRaw;
          try { fixtureRaw = fs.readFileSync(fixturePath, 'utf8'); }
          catch (e) {
            // try relative to project
            try { fixtureRaw = fs.readFileSync(`../${fixturePath}`, 'utf8'); }
            catch (e2) { errors.push(`missing fixture file: ${fixturePath}`); continue; }
          }
          let fixture;
          try { fixture = JSON.parse(fixtureRaw); } catch (e) { errors.push(`invalid json fixture ${fixturePath}: ${e.message}`); continue; }
          const ok = validateOut(fixture);
          if (!ok) errors.push(...(validateOut.errors || []).map(e => `fixture ${fixturePath}: ${e.instancePath} ${e.message}`));
        }
      }
      if (errors.length) fail(errors);
    }
  } catch (e) { fail('fixture validation error: ' + e.message); }

  console.log('Contract and fixtures validated');
  process.exit(0);
} catch (e) {
  fail(e.message);
}
