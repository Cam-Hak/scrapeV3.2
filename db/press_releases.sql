CREATE DATABASE tns;
USE tns;

CREATE TABLE `press_release` (
  `pr_id` int(11) NOT NULL AUTO_INCREMENT,
  `dt_id` int(11) NOT NULL DEFAULT '1',
  `headline` varchar(255) DEFAULT NULL,
  `a_id` int(11) DEFAULT NULL,
  `headline2` varchar(255) NOT NULL DEFAULT '',
  `content_date` date DEFAULT NULL,
  `body_txt` text,
  `contact_info` blob,
  `create_date` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_action` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status` char(1) DEFAULT NULL,
  `uname` varchar(15) DEFAULT NULL,
  `filename` varchar(100) DEFAULT NULL,
  `invoice_tag` varchar(50) DEFAULT NULL,
  `location` varchar(100) DEFAULT NULL,
  `orig_txt` blob,
  `h_err_flag` char(2) DEFAULT NULL,
  `b_err_flag` char(2) DEFAULT NULL,
  `ci_err_flag` char(2) DEFAULT NULL,
  `i_err_flag` char(2) DEFAULT NULL,
  `f_err_flag` char(2) DEFAULT NULL,
  `c_err_flag` char(2) DEFAULT NULL,
  `nexis_sent` datetime DEFAULT NULL,
  `factiva_sent` datetime DEFAULT NULL,
  `newsbank_sent` datetime DEFAULT NULL,
  `sent_by` varchar(15) DEFAULT NULL,
  `nexis_err` blob,
  `factiva_err` blob,
  `newsbank_err` text,
  `dialog_sent` datetime DEFAULT NULL,
  `dialog_err` text,
  `proquest_sent` datetime DEFAULT NULL,
  `proquest_err` text,
  `llesiant_sent` datetime DEFAULT NULL,
  `llesiant_err` text,
  `wisers_sent` datetime DEFAULT NULL,
  `wisers_err` text,
  `reuters_sent` datetime DEFAULT NULL,
  PRIMARY KEY (`pr_id`),
  UNIQUE KEY `filename_uniq_idx` (`filename`)
 
) ENGINE=InnoDB  DEFAULT CHARSET=latin1;

drop table press_release;
 
truncate press_release;
select * from press_release;

show engine innodb status;
SELECT COUNT(*) from press_release;