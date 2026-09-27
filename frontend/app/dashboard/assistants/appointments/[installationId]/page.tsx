import AppointmentConfiguratorClient from './AppointmentConfiguratorClient';

export default function AppointmentConfiguratorPage({ params }: { params: { installationId: string } }) {
  return <AppointmentConfiguratorClient installationId={params.installationId} />;
}
