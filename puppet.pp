# fragment
  $slack_json_loc = '/root/scripts/slack.json'
  $osrc_loc = '/root/adminrc'
  $hammers_ver = '0.1.8'

  file { '/usr/bin/pip-python':
    ensure => 'link',
    target => '/usr/bin/pip',
  } ->
  package { 'bag-o-hammers':
    provider => pip,
    name     => hammers,
    ensure   => $hammers_ver,
  } <-
  file { $slack_json_loc:
    source  => 'puppet:///files/slack.json',
    ensure  => present,
    mode    => '644',
    owner   => 'root',
    group   => 'root',
  }

  # Setting up the crons
  cron { 'floatingip_reaper':
      require => Package["bag-o-hammers"],
      command => "source $osrc_loc; (/usr/bin/neutron-reaper ip 14 --slack $slack_json_loc | /usr/bin/neutron) 2>&1 | /usr/bin/logger -t chameleon-chi-hammers-neutron_reaper-fip",
      user    => 'root',
      minute  => 10,
      hour    => 1,
  }
  cron { 'port_reaper':
      require => Package["bag-o-hammers"],
      command => "source $osrc_loc; (/usr/bin/neutron-reaper port 14 --slack $slack_json_loc | /usr/bin/neutron) 2>&1 | /usr/bin/logger -t chameleon-chi-hammers-neutron_reaper-port",
      user    => 'root',
      minute  => 15,
      hour    => 1,
  }
  cron { 'port_conflicts':
      require => Package["bag-o-hammers"],
      command => "/usr/bin/conflict-macs delete --osrc $osrc_loc --slack $slack_json_loc 2>&1 | /usr/bin/logger -t chameleon-chi-hammers-conflict_macs",
      user    => 'root',
      minute  => 20,
      hour    => '*/3',
  }
  cron { 'undead_instances':
      require => Package["bag-o-hammers"],
      command => "/usr/bin/undead-instances delete --osrc $osrc_loc --slack $slack_json_loc 2>&1 | /usr/bin/logger -t chameleon-chi-hammers-undead_instances",
      user    => 'root',
      minute  => 21,
      hour    => '*/3',
  }
  cron { 'retry_ipmi':
      require => Package["bag-o-hammers"],
      command => "/usr/bin/retry-ipmi reset --osrc $osrc_loc --slack $slack_json_loc 2>&1 | /usr/bin/logger -t chameleon-chi-hammers-retry_ipmi",
      user    => 'root',
      minute  => 22,
      hour    => '*/3',
  }
